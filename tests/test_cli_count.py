"""Tests CLI del subcomando count-market (Feature 25: R3).

Todos offline: silver construido en tmp_path, sin red, sin modelo entrenado.

Trazabilidad (tasks.md):
  R3 <- test_count_market_cards_shots_sot_json
         test_subcomandos_exactos_intactos
         test_stat_invalido_error
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from src import cli


# ---------------------------------------------------------------------------
# Helper: construye silver minimo con todas las stats en tmp_path
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
        rows: Lista de dicts con campos de partidos; el resto se rellena con defaults.

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
# Datos minimos para ARG y BRA (con las tres stats)
# ---------------------------------------------------------------------------

_ROWS_BASE = [
    {
        "date": "2026-06-01", "home_code": "ARG", "away_code": "BRA",
        "home_cards": 3.0, "away_cards": 2.0,
        "home_shots": 18.0, "away_shots": 12.0,
        "home_shots_on_target": 7.0, "away_shots_on_target": 4.0,
        "home_corners": 11.0, "away_corners": 4.0,
    },
    {
        "date": "2026-06-02", "home_code": "MEX", "away_code": "ARG",
        "home_cards": 1.0, "away_cards": 4.0,
        "home_shots": 10.0, "away_shots": 20.0,
        "home_shots_on_target": 3.0, "away_shots_on_target": 8.0,
        "home_corners": 5.0, "away_corners": 12.0,
    },
    {
        "date": "2026-06-03", "home_code": "ARG", "away_code": "USA",
        "home_cards": 2.0, "away_cards": 3.0,
        "home_shots": 22.0, "away_shots": 9.0,
        "home_shots_on_target": 9.0, "away_shots_on_target": 3.0,
        "home_corners": 10.0, "away_corners": 3.0,
    },
    {
        "date": "2026-06-04", "home_code": "BRA", "away_code": "MEX",
        "home_cards": 2.0, "away_cards": 1.0,
        "home_shots": 15.0, "away_shots": 11.0,
        "home_shots_on_target": 6.0, "away_shots_on_target": 4.0,
        "home_corners": 7.0, "away_corners": 6.0,
    },
]

# Conjunto EXACTO de subcomandos esperados (R3 feature 25 añade count-market)
EXPECTED_SUBCOMMANDS = frozenset(
    {
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
        "corners",
        "count-market",  # Feature 25
    }
)


# ---------------------------------------------------------------------------
# Helper de invocacion
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Ejecuta main(argv) capturando stdout/stderr.

    Args:
        argv: Lista de argumentos del CLI.

    Returns:
        Tuple (exit_code, stdout, stderr).
    """
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out_buf, err_buf
    try:
        exit_code = cli.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return exit_code, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# R3 — test_count_market_cards_shots_sot_json
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stat,expected_lines", [
    ("cards", [2.5, 3.5, 4.5]),
    ("shots", [20.5, 24.5, 28.5]),
    ("sot", [6.5, 8.5, 10.5]),
])
def test_count_market_cards_shots_sot_json(
    tmp_path: Path,
    stat: str,
    expected_lines: list[float],
) -> None:
    """count-market --stat <stat> --json: produce JSON valido con O/U correctas (R3)."""
    silver = _make_silver_csv(tmp_path, _ROWS_BASE)
    as_of = "2026-06-10"

    exit_code, stdout, stderr = _run(
        [
            "count-market", "ARG", "BRA",
            "--stat", stat,
            "--as-of", as_of,
            "--silver", str(silver),
            "--json",
        ]
    )

    assert exit_code == 0, f"[{stat}] exit_code esperado 0, got {exit_code}; stderr={stderr}"
    doc = json.loads(stdout)

    # Estructura basica
    assert doc["home"]["code"] == "ARG"
    assert doc["away"]["code"] == "BRA"
    assert doc["stat"] == stat
    assert doc["as_of"] == as_of

    # Lambdas positivos
    assert doc["lambda_home"] > 0.0, f"[{stat}] lambda_home debe ser > 0"
    assert doc["lambda_away"] > 0.0, f"[{stat}] lambda_away debe ser > 0"
    assert doc["lambda_total"] > 0.0, f"[{stat}] lambda_total debe ser > 0"
    assert abs(doc["lambda_total"] - (doc["lambda_home"] + doc["lambda_away"])) < 1e-9

    # Lineas correctas
    total_lines = [ou["line"] for ou in doc["total_ou"]]
    assert total_lines == expected_lines, (
        f"[{stat}] lineas esperadas {expected_lines}, got {total_lines}"
    )

    # over + under = 1 en cada linea
    for ou in doc["total_ou"] + doc["home_ou"] + doc["away_ou"]:
        total = ou["over"] + ou["under"]
        assert abs(total - 1.0) < 1e-9, (
            f"[{stat}] over+under={total:.10f} para linea {ou['line']}"
        )

    # noisy_note: cards tiene, shots y sot no
    if stat == "cards":
        assert doc["noisy_note"] is not None, "cards: noisy_note debe ser no-None"
    else:
        assert doc["noisy_note"] is None, f"[{stat}]: noisy_note debe ser None"


def test_count_market_salida_humana(tmp_path: Path) -> None:
    """count-market sin --json imprime lineas con el simbolo checkmark (R3)."""
    silver = _make_silver_csv(tmp_path, _ROWS_BASE)
    exit_code, stdout, stderr = _run(
        [
            "count-market", "ARG", "BRA",
            "--stat", "shots",
            "--silver", str(silver),
        ]
    )
    assert exit_code == 0, f"exit_code esperado 0; stderr={stderr}"
    assert "✅" in stdout, "Salida humana debe contener ✅"
    assert "Tiros" in stdout, "Salida humana debe mencionar 'Tiros'"


def test_count_market_cards_aviso_en_salida_humana(tmp_path: Path) -> None:
    """count-market --stat cards imprime aviso de ruido en stdout (R3, R4)."""
    silver = _make_silver_csv(tmp_path, _ROWS_BASE)
    exit_code, stdout, stderr = _run(
        [
            "count-market", "ARG", "BRA",
            "--stat", "cards",
            "--silver", str(silver),
        ]
    )
    assert exit_code == 0, f"exit_code esperado 0; stderr={stderr}"
    # El aviso de ruido debe aparecer (⚠️ o nota)
    assert "⚠️" in stdout or "ruido" in stdout.lower() or "arbitro" in stdout.lower(), (
        "Salida de cards debe incluir aviso de ruido"
    )


def test_count_market_lineas_custom(tmp_path: Path) -> None:
    """count-market --lines custom: usa esas lineas en la respuesta JSON (R3)."""
    silver = _make_silver_csv(tmp_path, _ROWS_BASE)
    exit_code, stdout, stderr = _run(
        [
            "count-market", "ARG", "BRA",
            "--stat", "cards",
            "--lines", "1.5,2.5",
            "--silver", str(silver),
            "--json",
        ]
    )
    assert exit_code == 0, f"exit_code esperado 0; stderr={stderr}"
    doc = json.loads(stdout)
    total_lines = [ou["line"] for ou in doc["total_ou"]]
    assert total_lines == [1.5, 2.5], f"lineas custom esperadas [1.5, 2.5], got {total_lines}"


# ---------------------------------------------------------------------------
# R3 — test_subcomandos_exactos_intactos
# ---------------------------------------------------------------------------


def test_subcomandos_exactos_intactos() -> None:
    """R3: el parser tiene EXACTAMENTE 18 subcomandos; previos intactos + count-market."""
    parser = cli.build_parser()
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "_name_parser_map"):
            subparsers_action = action
            break

    assert subparsers_action is not None, "No se encontraron subparsers en el parser"
    actual = frozenset(subparsers_action._name_parser_map.keys())

    assert actual == EXPECTED_SUBCOMMANDS, (
        f"Diferencia: extra={actual - EXPECTED_SUBCOMMANDS}, "
        f"faltantes={EXPECTED_SUBCOMMANDS - actual}"
    )


# ---------------------------------------------------------------------------
# R3 — test_stat_invalido_error
# ---------------------------------------------------------------------------


def test_stat_invalido_error(tmp_path: Path) -> None:
    """count-market --stat invalido falla con exit code no-cero (R3)."""
    silver = _make_silver_csv(tmp_path, _ROWS_BASE)
    # argparse captura el --stat invalido y llama a SystemExit(2)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "count-market", "ARG", "BRA",
                "--stat", "invalid_stat",
                "--silver", str(silver),
            ]
        )
    assert exc_info.value.code != 0, (
        f"--stat invalido debe salir con codigo != 0, got {exc_info.value.code}"
    )


def test_stat_requerido_falta(tmp_path: Path) -> None:
    """count-market sin --stat falla con exit code no-cero (R3)."""
    silver = _make_silver_csv(tmp_path, _ROWS_BASE)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["count-market", "ARG", "BRA", "--silver", str(silver)])
    assert exc_info.value.code != 0, (
        f"--stat ausente debe salir con codigo != 0, got {exc_info.value.code}"
    )


def test_count_market_silver_ausente() -> None:
    """count-market con silver inexistente retorna exit code 1 (R3)."""
    exit_code, stdout, stderr = _run(
        [
            "count-market", "ARG", "BRA",
            "--stat", "shots",
            "--silver", "/ruta/inexistente/matches.csv",
        ]
    )
    assert exit_code == 1, f"exit_code esperado 1, got {exit_code}"
    assert "error" in stderr.lower(), f"stderr debe contener mensaje de error"


def test_count_market_mismo_equipo() -> None:
    """count-market con HOME==AWAY retorna exit code 1 (R3)."""
    exit_code, stdout, stderr = _run(
        ["count-market", "ARG", "ARG", "--stat", "cards"]
    )
    assert exit_code == 1, f"exit_code esperado 1, got {exit_code}"
    assert "error" in stderr.lower()


def test_count_market_codigo_invalido() -> None:
    """count-market con codigo FIFA invalido retorna exit code 1 (R3)."""
    exit_code, stdout, stderr = _run(
        ["count-market", "XYZ", "BRA", "--stat", "shots"]
    )
    assert exit_code == 1, f"exit_code esperado 1, got {exit_code}"
