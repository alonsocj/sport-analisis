"""R1–R7 — normalización bronze → silver (offline; fixtures en tests/fixtures/feature_store)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pandas as pd
import pytest

from src.features.silver import (
    SILVER_COLUMNS,
    STAT_COLUMNS,
    SilverInputError,
    build_silver,
    make_match_id,
    resolve_code,
    slugify,
    write_silver,
)
from src.ingestion.teams import all_teams

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "feature_store"


def _bronze(tmp_path: Path, api: bool = True, public: bool = True) -> Path:
    """Arma un directorio bronze temporal copiando las fixtures deterministas."""
    bronze = tmp_path / "bronze"
    bronze.mkdir(parents=True, exist_ok=True)
    if api:
        shutil.copytree(FIXTURES / "fixtures", bronze / "fixtures")
        shutil.copytree(FIXTURES / "fixtures_statistics", bronze / "fixtures_statistics")
    if public:
        (bronze / "public_results").mkdir()
        shutil.copy(
            FIXTURES / "public_results" / "results.csv",
            bronze / "public_results" / "results.csv",
        )
    return bronze


def test_extrae_fixtures_ft_y_descarta_no_finalizados(tmp_path):
    # R1: extrae FT (fecha UTC, equipos, goles, torneo); descarta status != FT.
    df = build_silver(_bronze(tmp_path, public=False))

    assert len(df) == 2  # la fixture trae 2 FT + 1 NS (descartada)
    mex = df[df["home_code"] == "MEX"].iloc[0]
    assert mex["date"] == "2026-03-25"
    assert mex["away_code"] == "ARG"
    assert mex["home_goals"] == 2 and mex["away_goals"] == 1
    assert mex["tournament"] == "Friendlies"  # league.name (sin contraparte pública)
    esp = df[df["home_code"] == "ESP"].iloc[0]
    assert esp["date"] == "2026-03-28"  # 2026-03-29T01:30+02:00 → YYYY-MM-DD en UTC
    assert esp["away_code"] == "FRA"
    assert esp["tournament"] == "UEFA Nations League"
    assert (df["source"] == "api_football").all()


def test_adjunta_stats_y_posesion_float(tmp_path):
    # R2: adjunta córners, tarjetas, tiros, tiros a puerta y posesión ("55%" → 55.0).
    df = build_silver(_bronze(tmp_path, public=False))

    row = df[df["home_code"] == "MEX"].iloc[0]
    assert row["home_possession"] == 55.0
    assert isinstance(row["home_possession"], float)
    assert row["away_possession"] == 45.0
    assert row["home_corners"] == 7.0 and row["away_corners"] == 3.0
    assert row["home_cards"] == 3.0  # 2 amarillas + 1 roja
    assert row["away_cards"] == 1.0
    assert row["home_shots"] == 12.0 and row["away_shots"] == 6.0
    assert row["home_shots_on_target"] == 5.0 and row["away_shots_on_target"] == 2.0


def test_sin_statistics_columnas_nulas(tmp_path):
    # R2: sin archivo de statistics → columnas de stats nulas, sin fallar.
    df = build_silver(_bronze(tmp_path, public=False))

    esp = df[df["home_code"] == "ESP"].iloc[0]  # fixture 2002 no tiene statistics
    assert esp[list(STAT_COLUMNS)].isna().all()


def test_carga_csv_publico_stats_nulas(tmp_path):
    # R3: filas del CSV público con source='public_csv' y todas las stats nulas.
    df = build_silver(_bronze(tmp_path, api=False))

    assert len(df) == 6
    assert (df["source"] == "public_csv").all()
    assert df[list(STAT_COLUMNS)].isna().all().all()
    arg = df[(df["home_code"] == "ARG") & (df["away_code"] == "BRA")].iloc[0]
    assert bool(arg["neutral"]) is True  # neutral TRUE → bool
    usa = df[(df["home_code"] == "USA") & (df["away_code"] == "CAN")].iloc[0]
    assert bool(usa["neutral"]) is False
    assert usa["home_goals"] == 1 and usa["away_goals"] == 1  # scores → int


def test_filas_publicas_corruptas_descartadas_sin_fallar(tmp_path):
    # R3: filas con goles no numéricos ('NA' del calendario del Mundial 2026) o fecha
    # no parseable como YYYY-MM-DD se descartan y el lote continúa sin excepción
    # (coherente con R5 de ingesta_publica). El resto de filas se carga.
    bronze = tmp_path / "bronze"
    (bronze / "public_results").mkdir(parents=True)
    (bronze / "public_results" / "results.csv").write_text(
        "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
        "2026-06-11,Mexico,Canada,NA,NA,FIFA World Cup,Mexico City,Mexico,FALSE\n"
        "11/06/2026,Spain,France,1,0,Friendly,Paris,France,TRUE\n"
        "2025-10-10,Argentina,Brazil,2,2,Friendly,Lima,Peru,TRUE\n",
        encoding="utf-8",
    )

    df = build_silver(bronze)  # sin excepción

    assert len(df) == 1  # solo la fila válida sobrevive
    row = df.iloc[0]
    assert row["home_code"] == "ARG" and row["away_code"] == "BRA"
    assert row["home_goals"] == 2 and row["away_goals"] == 2
    assert row["source"] == "public_csv"


def test_codigos_fifa_y_alias(tmp_path):
    # R4: nombres de la fuente → códigos FIFA de 3 letras vía las 48 + tabla de alias.
    df = build_silver(_bronze(tmp_path, api=False))

    jpn = df[df["date"] == "2025-06-15"].iloc[0]
    assert jpn["home_code"] == "JPN"  # 'Japan'
    assert jpn["away_code"] == "KOR"  # 'South Korea' (alias dataset → KOR)
    assert jpn["away_team"] == "South Korea"  # nombre canónico de teams.py
    usa = df[df["date"] == "2024-07-01"].iloc[0]
    assert usa["home_code"] == "USA"  # 'United States' → USA
    fifa_codes = {t.code for t in all_teams()}
    assert {"JPN", "KOR", "USA", "CAN", "MEX", "ARG", "BRA", "GER"} <= fifa_codes


def test_fallback_slug_determinista_conserva_partido(tmp_path):
    # R4: fuera de las 48 → slug determinista y el partido SE CONSERVA en silver.
    df = build_silver(_bronze(tmp_path, api=False))

    wales = df[df["date"] == "2025-11-14"]
    assert len(wales) == 1  # el partido Wales-Finland se conserva (red completa, R19)
    row = wales.iloc[0]
    assert row["home_code"] == "wales"
    assert row["away_code"] == "finland"
    assert row["home_team"] == "Wales"  # fuera de 48 → nombre de la fuente tal cual
    fifa_codes = {t.code for t in all_teams()}
    assert row["home_code"] not in fifa_codes  # sin colisión con códigos FIFA
    # Determinismo del fallback (no depende de PYTHONHASHSEED).
    assert resolve_code("Wales") == resolve_code("Wales") == "wales"
    assert slugify("São Tomé and Príncipe") == "sao_tome_and_principe"


def test_match_id_estable(tmp_path):
    # R5: match_id determinista y estable entre ejecuciones (hash corto vía hashlib).
    bronze = _bronze(tmp_path)
    ids_1 = list(build_silver(bronze)["match_id"])
    ids_2 = list(build_silver(bronze)["match_id"])

    assert ids_1 == ids_2
    assert all(len(i) == 12 for i in ids_1)
    expected = hashlib.sha1(b"public_csv|2025-06-15|JPN|KOR").hexdigest()[:12]
    assert make_match_id("public_csv", "2025-06-15", "JPN", "KOR") == expected


def test_dedupe_prioriza_api_football(tmp_path):
    # R6: partido en ambas fuentes → una única fila api_football, con neutral y
    # tournament tomados del registro público.
    df = build_silver(_bronze(tmp_path))

    assert len(df) == 7  # 2 API + 6 público − 1 duplicado
    dup = df[(df["date"] == "2026-03-25") & (df["home_code"] == "MEX") & (df["away_code"] == "ARG")]
    assert len(dup) == 1
    row = dup.iloc[0]
    assert row["source"] == "api_football"  # prioridad a la fuente con estadísticas
    assert bool(row["neutral"]) is True  # del registro público (TRUE)
    assert row["tournament"] == "Friendly"  # del registro público (no 'Friendlies')
    assert row["home_possession"] == 55.0  # conserva las stats de la API


def test_matches_csv_esquema_contrato(tmp_path):
    # R7: matches.csv con exactamente el esquema, tipos y orden de columnas del contrato.
    df = build_silver(_bronze(tmp_path))
    path = write_silver(df, tmp_path / "silver")

    assert path.name == "matches.csv"
    out = pd.read_csv(path)
    assert list(out.columns) == list(SILVER_COLUMNS)
    assert out["home_goals"].dtype.kind == "i"  # int
    assert out["away_goals"].dtype.kind == "i"
    assert out["neutral"].dtype.kind == "b"  # bool True/False
    for col in STAT_COLUMNS:
        assert out[col].dtype.kind == "f"  # float nullable (null → celda vacía)
    # Orden de filas determinista: (date, match_id) ascendente.
    assert out[["date", "match_id"]].equals(
        out[["date", "match_id"]].sort_values(["date", "match_id"]).reset_index(drop=True)
    )


def test_continua_con_una_sola_fuente(tmp_path):
    # R7: si falta una de las dos fuentes bronze, continúa con la disponible.
    solo_api = build_silver(_bronze(tmp_path / "a", public=False))
    assert len(solo_api) == 2 and (solo_api["source"] == "api_football").all()

    solo_publico = build_silver(_bronze(tmp_path / "b", api=False))
    assert len(solo_publico) == 6 and (solo_publico["source"] == "public_csv").all()


def test_sin_fuentes_error_claro(tmp_path):
    # R7: sin ninguna fuente bronze → error claro.
    vacio = tmp_path / "bronze"
    vacio.mkdir()
    with pytest.raises(SilverInputError, match="fixtures"):
        build_silver(vacio)
