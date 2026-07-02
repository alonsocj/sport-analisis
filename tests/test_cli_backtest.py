"""Feature 5 — backtesting CLI (R10).

Tests del subcomando ``backtest`` en ``src/cli.py``. 100 % offline y deterministas:
- test_backtest_exito_y_reporte: con silver sintetico, verifica exit 0 y reporte.
- test_errores_accionables_exit_codes: silver ausente → exit 1, error accionable.
- test_subcomandos_previos_intactos: los 6 subcomandos originales siguen disponibles.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

import src.cli as cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEAMS = ["AAA", "BBB", "CCC", "DDD"]


def _make_silver(path: Path, n_per_pair: int = 20) -> None:
    """Genera un CSV silver sintetico con TEAMS cruzados.

    Args:
        path: Output path for the CSV.
        n_per_pair: Number of matches per ordered team pair.
    """
    import itertools

    header = "match_id,date,home_code,away_code,home_goals,away_goals,neutral"
    rows = []
    mid = 1
    cur = date(2020, 1, 1)
    for home, away in itertools.permutations(TEAMS, 2):
        for _ in range(n_per_pair):
            rows.append(
                f"{mid},{cur.isoformat()},{home},{away},{mid % 3},{(mid + 1) % 3},False"
            )
            mid += 1
            cur += timedelta(days=7)

    path.write_text("\n".join([header] + rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# R10 — test_backtest_exito_y_reporte
# ---------------------------------------------------------------------------


def test_backtest_exito_y_reporte(tmp_path, monkeypatch, capsys):
    """R10: con silver sintetico inyectado, backtest termina exit 0 y escribe el reporte."""
    from src.backtest import walkforward

    silver = tmp_path / "silver" / "matches.csv"
    silver.parent.mkdir(parents=True)
    _make_silver(silver, n_per_pair=20)
    out_dir = tmp_path / "backtest_out"

    monkeypatch.setattr(walkforward, "DEFAULT_SILVER_PATH", silver)
    monkeypatch.setattr(cli, "DEFAULT_BACKTEST_SILVER", silver)

    exit_code = cli.main([
        "backtest",
        "--from-date", "2024-01-01",
        "--to-date", "2024-02-28",
        "--refit-every", "month",
        "--out", str(out_dir),
    ])

    assert exit_code == 0, f"Esperado exit 0, obtenido {exit_code}"

    # Archivos de reporte generados
    assert (out_dir / "summary.json").is_file(), "summary.json no existe"
    assert (out_dir / "windows.csv").is_file(), "windows.csv no existe"
    assert (out_dir / "calibration.csv").is_file(), "calibration.csv no existe"

    # Stdout contiene el checkmark y metricas reconocibles
    captured = capsys.readouterr()
    assert "✅" in captured.out, "Falta '✅' en stdout"
    assert any(
        kw in captured.out.lower() for kw in ("backtest", "log_loss", "brier", "accuracy")
    ), f"Metricas no encontradas en stdout: {captured.out!r}"

    # summary.json valido con campos requeridos
    data = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert "metrics" in data, "summary.json no tiene 'metrics'"
    assert "model" in data["metrics"], "summary.json['metrics'] no tiene 'model'"
    assert "as_of" in data, "summary.json no tiene 'as_of'"


def test_backtest_exito_con_silver_custom(tmp_path, monkeypatch, capsys):
    """R10: backtest con silver inyectado via monkeypatch termina exit 0 y reporte."""
    from src.backtest import walkforward

    silver = tmp_path / "matches.csv"
    _make_silver(silver, n_per_pair=20)
    out_dir = tmp_path / "out"

    # Inyectar la constante DEFAULT_SILVER_PATH y DEFAULT_BACKTEST_SILVER en cli
    monkeypatch.setattr(walkforward, "DEFAULT_SILVER_PATH", silver)
    monkeypatch.setattr(cli, "DEFAULT_BACKTEST_SILVER", silver)

    exit_code = cli.main([
        "backtest",
        "--from-date", "2024-01-01",
        "--to-date", "2024-02-28",
        "--refit-every", "month",
        "--out", str(out_dir),
    ])

    assert exit_code == 0, f"Esperado exit 0, obtenido {exit_code}"

    captured = capsys.readouterr()
    assert "✅" in captured.out
    assert "Backtest" in captured.out or "backtest" in captured.out.lower()

    # Reporte generado en out_dir
    assert (out_dir / "summary.json").is_file()
    assert (out_dir / "windows.csv").is_file()
    assert (out_dir / "calibration.csv").is_file()

    # summary.json valido con campos requeridos
    data = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert "metrics" in data
    assert "model" in data["metrics"]
    assert "as_of" in data


# ---------------------------------------------------------------------------
# R10 — test_errores_accionables_exit_codes
# ---------------------------------------------------------------------------


def test_error_silver_ausente_exit_1(tmp_path, monkeypatch, capsys):
    """R10: silver ausente → error accionable en stderr y exit 1."""
    from src.backtest import walkforward

    ruta_inexistente = tmp_path / "no_existe" / "matches.csv"
    monkeypatch.setattr(cli, "DEFAULT_BACKTEST_SILVER", ruta_inexistente)
    monkeypatch.setattr(walkforward, "DEFAULT_SILVER_PATH", ruta_inexistente)

    exit_code = cli.main([
        "backtest",
        "--from-date", "2024-01-01",
        "--to-date", "2024-01-31",
        "--out", str(tmp_path / "out"),
    ])

    assert exit_code == 1

    captured = capsys.readouterr()
    err = captured.err.lower()
    assert "error:" in err
    # Mensaje accionable: menciona build-features o ingest-public
    assert "build-features" in err or "ingest-public" in err


def test_errores_accionables_exit_codes(tmp_path, monkeypatch, capsys):
    """R10: silver ausente → exit 1; argparse invalido → exit 2 (SystemExit)."""
    from src.backtest import walkforward

    ruta_inexistente = tmp_path / "no_existe.csv"
    monkeypatch.setattr(cli, "DEFAULT_BACKTEST_SILVER", ruta_inexistente)
    monkeypatch.setattr(walkforward, "DEFAULT_SILVER_PATH", ruta_inexistente)

    # Silver ausente → exit 1
    exit_code = cli.main([
        "backtest",
        "--from-date", "2024-01-01",
        "--out", str(tmp_path / "out"),
    ])
    assert exit_code == 1

    # --refit-every invalido → argparse exit 2 (SystemExit)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["backtest", "--refit-every", "biweekly"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# R10 — test_subcomandos_previos_intactos
# ---------------------------------------------------------------------------


def test_subcomandos_previos_intactos():
    """R10: los 6 subcomandos originales siguen disponibles e intactos."""
    import argparse

    parser = cli.build_parser()
    sub = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    # Los 6 originales siguen presentes
    originales = {
        "ingest-public", "build-features", "train", "predict", "schedule", "markets"
    }
    assert originales.issubset(set(sub.choices)), (
        f"Subcomandos faltantes: {originales - set(sub.choices)}"
    )
    # El nuevo 'backtest' esta presente
    assert "backtest" in set(sub.choices)

    # Funciones originales no han cambiado
    assert sub.choices["ingest-public"]._defaults.get("func") is cli.cmd_ingest_public
    assert sub.choices["build-features"]._defaults.get("func") is cli.cmd_build_features
    assert sub.choices["train"]._defaults.get("func") is cli.cmd_train
    assert sub.choices["predict"]._defaults.get("func") is cli.cmd_predict
    assert sub.choices["schedule"]._defaults.get("func") is cli.cmd_schedule
    assert sub.choices["markets"]._defaults.get("func") is cli.cmd_markets
    assert sub.choices["backtest"]._defaults.get("func") is cli.cmd_backtest
