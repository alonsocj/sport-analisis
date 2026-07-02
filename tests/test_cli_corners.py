"""Tests CLI del subcomando corners (Feature 24: R4).

Todos offline: silver construido en tmp_path, sin red, sin modelo entrenado.

Trazabilidad (tasks.md):
  R4 <- test_corners_basico_y_json
         test_subcomandos_exactos_intactos
         test_corners_errores_exit_codes
         test_corners_lines_custom
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from src import cli


# ---------------------------------------------------------------------------
# Helper: construye silver minimo con corners en tmp_path
# ---------------------------------------------------------------------------

_SILVER_COLUMNS = (
    "match_id", "date", "home_code", "away_code", "home_team", "away_team",
    "home_goals", "away_goals", "tournament", "neutral", "source",
    "home_corners", "away_corners",
    "home_cards", "away_cards", "home_shots", "away_shots",
    "home_shots_on_target", "away_shots_on_target",
    "home_possession", "away_possession", "home_xg", "away_xg",
)


def _make_silver_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Crea silver CSV con esquema completo en tmp_path.

    Args:
        tmp_path: Directorio temporal del test.
        rows: Lista de dicts con los campos minimos (date, home_code, away_code,
            home_corners, away_corners). El resto se rellena con defaults.

    Returns:
        Path al CSV creado.
    """
    full_rows = []
    for i, row in enumerate(rows):
        full_row: dict = {c: None for c in _SILVER_COLUMNS}
        full_row["match_id"] = f"m{i}"
        full_row["home_team"] = row.get("home_code", "")
        full_row["away_team"] = row.get("away_code", "")
        full_row["home_goals"] = 1
        full_row["away_goals"] = 1
        full_row["tournament"] = "WC"
        full_row["neutral"] = True
        full_row["source"] = "test"
        full_row.update(row)
        full_rows.append(full_row)

    path = tmp_path / "matches.csv"
    pd.DataFrame(full_rows, columns=list(_SILVER_COLUMNS)).to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Datos minimos para dos equipos (ARG y BRA)
# ---------------------------------------------------------------------------

_ROWS_BASE = [
    {"date": "2026-06-01", "home_code": "ARG", "away_code": "BRA",
     "home_corners": 11.0, "away_corners": 4.0},
    {"date": "2026-06-02", "home_code": "MEX", "away_code": "ARG",
     "home_corners": 5.0, "away_corners": 12.0},
    {"date": "2026-06-03", "home_code": "ARG", "away_code": "USA",
     "home_corners": 10.0, "away_corners": 3.0},
    {"date": "2026-06-04", "home_code": "BRA", "away_code": "MEX",
     "home_corners": 7.0, "away_corners": 6.0},
]


# ---------------------------------------------------------------------------
# R4 — salida basica (texto) y JSON
# ---------------------------------------------------------------------------


def test_corners_basico_y_json(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """cmd_corners imprime tabla human y JSON valido con estructura correcta (R4)."""
    silver = _make_silver_csv(tmp_path, _ROWS_BASE)

    # --- Salida human-readable ---
    code = cli.main(["corners", "ARG", "BRA", "--as-of", "2026-06-10",
                     "--silver", str(silver)])
    out, _ = capsys.readouterr()

    assert code == 0, f"Exit code {code} != 0"
    assert "ARG" in out
    assert "BRA" in out
    assert "O8.5" in out or "O9.5" in out  # lineas por defecto presentes
    assert "over" in out.lower()

    # --- Salida JSON ---
    code_j = cli.main(["corners", "ARG", "BRA", "--as-of", "2026-06-10",
                       "--silver", str(silver), "--json"])
    out_j, _ = capsys.readouterr()

    assert code_j == 0, f"JSON exit code {code_j} != 0"
    doc = json.loads(out_j)

    # Estructura requerida (design.md)
    assert doc["home"]["code"] == "ARG"
    assert doc["away"]["code"] == "BRA"
    assert "lambda_home" in doc
    assert "lambda_away" in doc
    assert "lambda_total" in doc
    assert "mu_global" in doc
    assert "n_matches_home" in doc
    assert "n_matches_away" in doc
    assert "k" in doc
    assert "total_ou" in doc
    assert "home_ou" in doc
    assert "away_ou" in doc

    # Cada linea: over + under = 1.0
    for entry in doc["total_ou"]:
        total = entry["over"] + entry["under"]
        assert abs(total - 1.0) < 1e-9, (
            f"total_ou linea {entry['line']}: over+under={total}"
        )

    # lambda_total = lambda_home + lambda_away
    assert abs(doc["lambda_total"] - (doc["lambda_home"] + doc["lambda_away"])) < 1e-9


# ---------------------------------------------------------------------------
# R4 — Subcomandos exactos: 16 previos + corners = 17
# ---------------------------------------------------------------------------


def test_subcomandos_exactos_intactos() -> None:
    """El parser tiene exactamente 17 subcomandos: 16 previos + 'corners' (R4)."""
    parser = cli.build_parser()
    sub = None
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices is not None:
            sub = action
            break

    assert sub is not None, "No se encontro el subparser en el parser"

    previos_17 = {
        "ingest-public",
        "build-features",
        "train",
        "predict",
        "schedule",
        "markets",
        "backtest",
        "predict-log",
        "evaluate",
        "ingest-goalscorers",
        "scorers",
        "simulate",
        "ingest-elo",
        "ingest-wiki-stats",
        "ingest-roster",
        "ingest-fotmob-stats",
        "count-market",  # Feature 25
    }
    esperados = previos_17 | {"corners"}

    assert set(sub.choices) == esperados, (
        f"Subcomandos inesperados.\n"
        f"  Faltantes: {esperados - set(sub.choices)}\n"
        f"  Sobrantes: {set(sub.choices) - esperados}"
    )
    assert len(set(sub.choices)) == 18, (
        f"Esperados 18 subcomandos, got {len(set(sub.choices))}"
    )


# ---------------------------------------------------------------------------
# R4 — Exit codes de error
# ---------------------------------------------------------------------------


def test_corners_errores_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Errores de dominio producen exit_code=1 con mensaje util (R4)."""
    silver = _make_silver_csv(tmp_path, _ROWS_BASE)

    # Codigo FIFA invalido
    code = cli.main(["corners", "INVALID", "BRA", "--silver", str(silver)])
    assert code == 1, "Codigo invalido debe devolver 1"
    capsys.readouterr()

    # HOME == AWAY
    code = cli.main(["corners", "ARG", "ARG", "--silver", str(silver)])
    assert code == 1, "HOME==AWAY debe devolver 1"
    capsys.readouterr()

    # Silver inexistente
    code = cli.main(["corners", "ARG", "BRA",
                     "--silver", str(tmp_path / "noexiste.csv")])
    assert code == 1, "Silver inexistente debe devolver 1"
    capsys.readouterr()


# ---------------------------------------------------------------------------
# R4 — Lineas custom via --lines
# ---------------------------------------------------------------------------


def test_corners_lines_custom(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """--lines 8.5,9.5 => JSON solo contiene esas dos lineas en total_ou (R4)."""
    silver = _make_silver_csv(tmp_path, _ROWS_BASE)

    code = cli.main(["corners", "ARG", "BRA", "--as-of", "2026-06-10",
                     "--silver", str(silver), "--json", "--lines", "8.5,9.5"])
    out, _ = capsys.readouterr()

    assert code == 0
    doc = json.loads(out)

    lines_total = {entry["line"] for entry in doc["total_ou"]}
    assert lines_total == {8.5, 9.5}, (
        f"Con --lines 8.5,9.5 esperamos solo esas lineas, got {lines_total}"
    )
