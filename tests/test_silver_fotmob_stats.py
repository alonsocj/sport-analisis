"""tests/test_silver_fotmob_stats.py — Tests del merge de stats fotmob en silver (Feature 23, R3).

Todos offline: fixtures bronze en tmp_path, sin red real.

Mapeo de trazabilidad:
- test_merge_pobla_columnas               → R3 (merge fotmob puebla columnas por date+equipos)
- test_sin_bronze_silver_identico_no_regresion → R3 (sin bronze fotmob → silver idéntico)
- test_xg_columnas_anadidas               → R3 (home_xg/away_xg en el esquema, default null)
- test_merge_orientacion_invertida_swap_correcto → R3/BUG2 (fotmob trae home/away al revés)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from src.features.silver import (
    SILVER_COLUMNS,
    STAT_COLUMNS,
    build_silver,
)


# ---------------------------------------------------------------------------
# Helpers de fixtures bronze
# ---------------------------------------------------------------------------


def _write_public_results_csv(bronze_dir: Path, rows: list[dict]) -> None:
    """Escribe data/bronze/public_results/results.csv con los datos dados."""
    dir_ = bronze_dir / "public_results"
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / "results.csv"
    fieldnames = ["date", "home_team", "away_team", "home_score", "away_score",
                  "tournament", "city", "country", "neutral"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_fotmob_stats_bronze(bronze_dir: Path, docs: list[dict]) -> None:
    """Escribe data/bronze/fotmob_stats/<slug>.json para cada doc."""
    stats_dir = bronze_dir / "fotmob_stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        slug = doc["page_url"].rsplit("/", 1)[-1].split("#")[0]
        path = stats_dir / f"{slug}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _minimal_public_row(date, home, away, hg, ag, neutral="False", tournament="Friendly") -> dict:
    """Fila mínima del CSV público con resultados enteros."""
    return {
        "date": date,
        "home_team": home,
        "away_team": away,
        "home_score": str(hg),
        "away_score": str(ag),
        "tournament": tournament,
        "city": "TestCity",
        "country": "TestCountry",
        "neutral": neutral,
    }


# ---------------------------------------------------------------------------
# R3: test_merge_pobla_columnas
# ---------------------------------------------------------------------------


def test_merge_pobla_columnas(tmp_path):
    """R3: con bronze fotmob_stats presente, el merge puebla las columnas por (date, home_code, away_code)."""
    bronze_dir = tmp_path / "bronze"

    # Bronze público: RSA 0-1 CAN
    _write_public_results_csv(
        bronze_dir,
        [_minimal_public_row("2026-06-15", "South Africa", "Canada", 0, 1,
                              tournament="FIFA World Cup")],
    )

    # Bronze fotmob_stats para RSA-CAN
    _write_fotmob_stats_bronze(
        bronze_dir,
        [
            {
                "match_id": "4519287",
                "page_url": "/matches/south-africa-vs-canada/17s1wd",
                "home_name": "South Africa",
                "away_name": "Canada",
                "date": "2026-06-15",
                "has_stats": True,
                "home": {
                    "possession": 41.0,
                    "xg": 0.13,
                    "shots": 6.0,
                    "shots_on_target": 3.0,
                    "corners": 1.0,
                    "cards": 2.0,
                },
                "away": {
                    "possession": 59.0,
                    "xg": 1.32,
                    "shots": 12.0,
                    "shots_on_target": 5.0,
                    "corners": 4.0,
                    "cards": 1.0,
                },
            }
        ],
    )

    df = build_silver(bronze_dir)

    assert len(df) == 1
    row = df.iloc[0]

    # Columnas avanzadas ya existentes, ahora pobladas
    assert row["home_corners"] == pytest.approx(1.0)
    assert row["away_corners"] == pytest.approx(4.0)
    assert row["home_cards"] == pytest.approx(2.0)
    assert row["away_cards"] == pytest.approx(1.0)
    assert row["home_shots"] == pytest.approx(6.0)
    assert row["away_shots"] == pytest.approx(12.0)
    assert row["home_shots_on_target"] == pytest.approx(3.0)
    assert row["away_shots_on_target"] == pytest.approx(5.0)
    assert row["home_possession"] == pytest.approx(41.0)
    assert row["away_possession"] == pytest.approx(59.0)

    # Columnas xG nuevas (F23)
    assert row["home_xg"] == pytest.approx(0.13, rel=1e-6)
    assert row["away_xg"] == pytest.approx(1.32, rel=1e-6)


def test_merge_por_date_home_away_exacto(tmp_path):
    """R3: el merge usa la clave (date, home_code, away_code); diferente fecha → no cruza."""
    bronze_dir = tmp_path / "bronze"

    # Dos partidos en el silver: RSA-CAN (15-Jun) y ESP-FRA (20-Jun)
    _write_public_results_csv(
        bronze_dir,
        [
            _minimal_public_row("2026-06-15", "South Africa", "Canada", 0, 1),
            _minimal_public_row("2026-06-20", "Spain", "France", 1, 0),
        ],
    )

    # Bronze fotmob solo para RSA-CAN
    _write_fotmob_stats_bronze(
        bronze_dir,
        [
            {
                "match_id": "4519287",
                "page_url": "/matches/south-africa-vs-canada/abc",
                "home_name": "South Africa",
                "away_name": "Canada",
                "date": "2026-06-15",
                "has_stats": True,
                "home": {"shots": 6.0, "xg": 0.13},
                "away": {"shots": 12.0, "xg": 1.32},
            }
        ],
    )

    df = build_silver(bronze_dir)
    assert len(df) == 2

    rsa = df[df["home_code"] == "RSA"].iloc[0]
    esp = df[df["home_code"] == "ESP"].iloc[0]

    # RSA tiene stats fotmob
    assert rsa["home_shots"] == pytest.approx(6.0)
    assert rsa["home_xg"] == pytest.approx(0.13)

    # ESP no tiene bronze fotmob → stats nulas
    assert pd.isna(esp["home_shots"])
    assert pd.isna(esp["home_xg"])
    assert pd.isna(esp["away_xg"])


def test_merge_no_sobreescribe_stats_api_football(tmp_path):
    """R3: el merge fotmob NO sobreescribe stats previas de api_football."""
    import shutil
    from tests.test_silver import _bronze

    # Usamos las fixtures de test_silver que ya tienen stats api_football (MEX-ARG)
    bronze_dir = _bronze(tmp_path)

    # Añadir bronze fotmob_stats para MEX-ARG con stats distintas
    _write_fotmob_stats_bronze(
        bronze_dir,
        [
            {
                "match_id": "fotmob_fake",
                "page_url": "/matches/mexico-vs-argentina/fakeslug",
                "home_name": "Mexico",
                "away_name": "Argentina",
                "date": "2026-03-25",
                "has_stats": True,
                "home": {"shots": 99.0, "xg": 9.9, "corners": 99.0},
                "away": {"shots": 99.0, "xg": 9.9, "corners": 99.0},
            }
        ],
    )

    df = build_silver(bronze_dir)
    mex = df[df["home_code"] == "MEX"].iloc[0]

    # Las stats de api_football (shots=12, corners=7) NO deben ser sobreescritas
    assert mex["home_shots"] == pytest.approx(12.0)
    assert mex["home_corners"] == pytest.approx(7.0)
    # xG sí viene de fotmob (era null antes de F23)
    assert mex["home_xg"] == pytest.approx(9.9)


# ---------------------------------------------------------------------------
# R3: test_sin_bronze_silver_identico_no_regresion
# ---------------------------------------------------------------------------


def test_sin_bronze_silver_identico_no_regresion(tmp_path):
    """R3: sin bronze fotmob_stats, las columnas avanzadas son null y home_xg/away_xg nulas."""
    bronze_dir = tmp_path / "bronze"

    _write_public_results_csv(
        bronze_dir,
        [_minimal_public_row("2026-06-15", "South Africa", "Canada", 0, 1,
                              tournament="FIFA World Cup")],
    )
    # SIN directorio fotmob_stats

    df = build_silver(bronze_dir)
    assert len(df) == 1
    row = df.iloc[0]

    # Columnas avanzadas heredadas: nulas (no hay api_football ni fotmob)
    for col in ("home_corners", "away_corners", "home_cards", "away_cards",
                "home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target",
                "home_possession", "away_possession"):
        assert pd.isna(row[col]), f"Se esperaba null en {col}, se obtuvo {row[col]}"

    # Nuevas columnas xG también nulas
    assert pd.isna(row["home_xg"]), "home_xg debe ser null sin fotmob bronze"
    assert pd.isna(row["away_xg"]), "away_xg debe ser null sin fotmob bronze"


def test_sin_bronze_silver_datos_basicos_intactos(tmp_path):
    """R3 (no-regresión): sin fotmob_stats, los datos básicos (goles, IDs, etc.) no cambian."""
    bronze_dir = tmp_path / "bronze"

    _write_public_results_csv(
        bronze_dir,
        [
            _minimal_public_row("2026-06-15", "South Africa", "Canada", 0, 1,
                                tournament="FIFA World Cup", neutral="True"),
            _minimal_public_row("2026-06-20", "Spain", "France", 2, 1),
        ],
    )

    df = build_silver(bronze_dir)
    assert len(df) == 2

    rsa = df[df["home_code"] == "RSA"].iloc[0]
    assert rsa["home_goals"] == 0
    assert rsa["away_goals"] == 1
    assert rsa["home_code"] == "RSA"
    assert rsa["away_code"] == "CAN"
    assert bool(rsa["neutral"]) is True
    assert rsa["tournament"] == "FIFA World Cup"

    esp = df[df["home_code"] == "ESP"].iloc[0]
    assert esp["home_goals"] == 2
    assert esp["away_goals"] == 1
    assert esp["home_code"] == "ESP"
    assert esp["away_code"] == "FRA"


def test_fotmob_stats_has_stats_false_no_puebla(tmp_path):
    """R3: bronze fotmob_stats con has_stats=False no puebla las columnas."""
    bronze_dir = tmp_path / "bronze"

    _write_public_results_csv(
        bronze_dir,
        [_minimal_public_row("2026-06-15", "South Africa", "Canada", 0, 1)],
    )

    # Bronze con has_stats=False
    _write_fotmob_stats_bronze(
        bronze_dir,
        [
            {
                "match_id": "4519287",
                "page_url": "/matches/south-africa-vs-canada/17s1wd",
                "home_name": "South Africa",
                "away_name": "Canada",
                "date": "2026-06-15",
                "has_stats": False,  # sin stats
                "home": {},
                "away": {},
            }
        ],
    )

    df = build_silver(bronze_dir)
    row = df.iloc[0]

    # Columnas nulas (has_stats=False → no se aplica merge)
    assert pd.isna(row["home_xg"])
    assert pd.isna(row["away_xg"])
    assert pd.isna(row["home_shots"])


# ---------------------------------------------------------------------------
# R3: test_xg_columnas_anadidas
# ---------------------------------------------------------------------------


def test_xg_columnas_anadidas_en_esquema():
    """R3: home_xg y away_xg están en STAT_COLUMNS y en SILVER_COLUMNS."""
    assert "home_xg" in STAT_COLUMNS
    assert "away_xg" in STAT_COLUMNS
    assert "home_xg" in SILVER_COLUMNS
    assert "away_xg" in SILVER_COLUMNS


def test_xg_columnas_tipo_float_en_csv(tmp_path):
    """R3: home_xg/away_xg son float64 al leer el CSV silver (incluso cuando son null)."""
    bronze_dir = tmp_path / "bronze"
    _write_public_results_csv(
        bronze_dir,
        [_minimal_public_row("2026-06-15", "South Africa", "Canada", 0, 1)],
    )

    df = build_silver(bronze_dir)
    from src.features.silver import write_silver

    csv_path = write_silver(df, tmp_path / "silver")
    out = pd.read_csv(csv_path)

    assert "home_xg" in out.columns
    assert "away_xg" in out.columns
    # float dtype (k=f) cuando la columna es null (read_csv la infiere como float64)
    assert out["home_xg"].dtype.kind == "f"
    assert out["away_xg"].dtype.kind == "f"


def test_esquema_silver_incluye_xg_al_final_de_stat_columns(tmp_path):
    """R3: el esquema de SILVER_COLUMNS termina con home_xg, away_xg tras las otras stats."""
    cols = list(SILVER_COLUMNS)
    assert cols[-2] == "home_xg"
    assert cols[-1] == "away_xg"


# ---------------------------------------------------------------------------
# R3 / BUG2: test_merge_orientacion_invertida_swap_correcto
# ---------------------------------------------------------------------------


def test_merge_orientacion_invertida_swap_correcto(tmp_path):
    """R3 (BUG2): fotmob trae orientación inversa a martj42 → stats se asignan al lado correcto.

    Escenario real confirmado: silver dice Haiti 0-2 Brazil (HAI=home, BRA=away),
    pero fotmob ingesta el partido con home_name='Brazil', away_name='Haiti'.
    El merge debe detectar la inversión y asignar:
    - stats fotmob home (Brazil) → silver away
    - stats fotmob away (Haiti)  → silver home
    """
    bronze_dir = tmp_path / "bronze"

    # Silver público: Haiti (home) 0-2 Brazil (away)
    _write_public_results_csv(
        bronze_dir,
        [_minimal_public_row("2026-06-15", "Haiti", "Brazil", 0, 2,
                             tournament="FIFA World Cup")],
    )

    # Bronze fotmob con orientación INVERSA: home=Brazil, away=Haiti
    _write_fotmob_stats_bronze(
        bronze_dir,
        [
            {
                "match_id": "9999001",
                "page_url": "/matches/brazil-vs-haiti/fotmobslug",  # fotmob ve BRA como home
                "home_name": "Brazil",   # fotmob home = silver away
                "away_name": "Haiti",    # fotmob away = silver home
                "date": "2026-06-15",
                "has_stats": True,
                "home": {  # estas son stats de Brazil (silver: away)
                    "shots": 18.0,
                    "xg": 2.45,
                    "corners": 7.0,
                    "cards": 1.0,
                    "possession": 65.0,
                },
                "away": {  # estas son stats de Haiti (silver: home)
                    "shots": 5.0,
                    "xg": 0.31,
                    "corners": 2.0,
                    "cards": 2.0,
                    "possession": 35.0,
                },
            }
        ],
    )

    df = build_silver(bronze_dir)
    assert len(df) == 1
    row = df.iloc[0]

    # Silver: home=HAI, away=BRA
    assert row["home_code"] == "HAI"
    assert row["away_code"] == "BRA"

    # Haiti (silver home) debe tener las stats de fotmob "away" (Haiti)
    assert row["home_shots"] == pytest.approx(5.0), "home_shots (HAI) debe ser 5.0 (fotmob away)"
    assert row["home_xg"] == pytest.approx(0.31, rel=1e-6), "home_xg (HAI) debe ser 0.31"
    assert row["home_corners"] == pytest.approx(2.0)
    assert row["home_cards"] == pytest.approx(2.0)
    assert row["home_possession"] == pytest.approx(35.0)

    # Brazil (silver away) debe tener las stats de fotmob "home" (Brazil)
    assert row["away_shots"] == pytest.approx(18.0), "away_shots (BRA) debe ser 18.0 (fotmob home)"
    assert row["away_xg"] == pytest.approx(2.45, rel=1e-6), "away_xg (BRA) debe ser 2.45"
    assert row["away_corners"] == pytest.approx(7.0)
    assert row["away_cards"] == pytest.approx(1.0)
    assert row["away_possession"] == pytest.approx(65.0)
