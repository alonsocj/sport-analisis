"""R19–R21 — orquestación bronze → silver → gold y contratos de los CSVs gold."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from src.features.build import TEAM_FEATURES_COLUMNS, build_all
from src.features.elo import HISTORY_COLUMNS
from src.ingestion.teams import all_teams

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "feature_store"

AS_OF = "2026-06-01"  # inyectada: todos los partidos de las fixtures son anteriores


def _bronze(tmp_path: Path) -> Path:
    bronze = tmp_path / "bronze"
    shutil.copytree(FIXTURES / "fixtures", bronze / "fixtures")
    shutil.copytree(FIXTURES / "fixtures_statistics", bronze / "fixtures_statistics")
    (bronze / "public_results").mkdir()
    shutil.copy(
        FIXTURES / "public_results" / "results.csv",
        bronze / "public_results" / "results.csv",
    )
    return bronze


def test_elo_history_csv_esquema_contrato(tmp_path):
    # R19: elo_history.csv con su esquema exacto, una fila por equipo y partido,
    # incluyendo equipos fuera de las 48 (Elo global).
    bronze = _bronze(tmp_path)
    summary = build_all(
        AS_OF, bronze_dir=bronze, silver_dir=tmp_path / "silver", gold_dir=tmp_path / "gold"
    )

    hist = pd.read_csv(tmp_path / "gold" / "elo_history.csv")
    assert list(hist.columns) == list(HISTORY_COLUMNS)
    assert len(hist) == 2 * summary["n_matches_silver"]  # 2 filas por partido
    assert "wales" in set(hist["code"])  # fuera de las 48, conservado (R4)
    assert "finland" in set(hist["opponent_code"])
    assert list(hist["date"]) == sorted(hist["date"])  # cronológico


def test_team_features_48_filas_esquema(tmp_path):
    # R20: exactamente una fila por cada una de las 48 selecciones, esquema del
    # contrato y elo vigente a as_of_date.
    bronze = _bronze(tmp_path)
    build_all(
        AS_OF, bronze_dir=bronze, silver_dir=tmp_path / "silver", gold_dir=tmp_path / "gold"
    )

    feats = pd.read_csv(tmp_path / "gold" / "team_features.csv")
    assert list(feats.columns) == list(TEAM_FEATURES_COLUMNS)
    codes = sorted(t.code for t in all_teams())
    assert len(feats) == len(codes) == 48
    assert list(feats["code"]) == codes  # solo las 48, orden ascendente
    assert (feats["as_of_date"] == AS_OF).all()

    mex = feats[feats["code"] == "MEX"].iloc[0]
    assert mex["matches_count"] == 1
    assert mex["gf_ma15"] == 2.0 and mex["ga_ma15"] == 1.0
    assert mex["possession_ma15"] == 55.0  # stats de la fila api_football
    assert mex["elo"] != 1500.0  # rating vigente tras su victoria

    sin_partidos = feats[feats["matches_count"] == 0]
    assert len(sin_partidos) >= 1  # selecciones sin histórico en las fixtures
    assert (sin_partidos["elo"] == 1500.0).all()  # rating inicial
    assert sin_partidos[["gf_ma15", "ga_ma15"]].isna().all().all()


def test_build_all_determinista_tres_csv(tmp_path):
    # R21: orquestación con as_of_date inyectada; escribe los 3 CSVs y es determinista
    # (misma entrada → mismos bytes). as_of_date inválida → ValueError claro.
    bronze = _bronze(tmp_path)
    out_1, out_2 = tmp_path / "o1", tmp_path / "o2"
    summary_1 = build_all(
        AS_OF, bronze_dir=bronze, silver_dir=out_1 / "silver", gold_dir=out_1 / "gold"
    )
    summary_2 = build_all(
        AS_OF, bronze_dir=bronze, silver_dir=out_2 / "silver", gold_dir=out_2 / "gold"
    )

    assert summary_1["n_matches_silver"] == summary_2["n_matches_silver"] == 7
    assert summary_1["n_teams_gold"] == summary_2["n_teams_gold"] == 48
    for parts in (("silver", "matches.csv"), ("gold", "elo_history.csv"), ("gold", "team_features.csv")):
        path_1, path_2 = out_1.joinpath(*parts), out_2.joinpath(*parts)
        assert path_1.is_file() and path_2.is_file()
        assert path_1.read_bytes() == path_2.read_bytes()  # byte a byte

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        build_all("06/01/2026", bronze_dir=bronze, silver_dir=out_1 / "s", gold_dir=out_1 / "g")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        build_all("2026-13-45", bronze_dir=bronze, silver_dir=out_1 / "s", gold_dir=out_1 / "g")
