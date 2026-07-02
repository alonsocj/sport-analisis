"""Tests del subcomando CLI ``markets`` (Feature 4, R7).

100% offline y deterministas: main(argv) se invoca EN PROCESO con params
sinteticos en tmp_path. Verifica salida humana y JSON, manejo de errores,
exit codes y que los subcomandos previos no cambian de comportamiento.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import src.cli as cli

# ---------------------------------------------------------------------------
# Helpers: reutilizamos el mismo helper de test_cli.py para construir JSON
# de parametros sinteticos sin duplicar la fixture de entrenamiento.
# ---------------------------------------------------------------------------

AS_OF = "2026-06-01"


def _make_params_doc(**overrides) -> dict:
    """JSON sintetico con las claves del contrato de la feature 3."""
    doc = {
        "as_of_date": AS_OF,
        "from_date": "2018-01-01",
        "xi": 0.65,
        "mu": 0.1,
        "home_advantage": 0.3,
        "rho": -0.08,
        "attack": {
            "ARG": 0.40, "BRA": -0.10, "JPN": -0.60,
            "MEX": 0.20, "USA": 0.10, "RSA": -0.30,
        },
        "defense": {
            "ARG": 0.30, "BRA": 0.20, "JPN": -0.50,
            "MEX": 0.05, "USA": 0.00, "RSA": -0.20,
        },
        "n_matches": 240,
        "n_teams": 6,
        "min_matches": 5,
        "reg_lambda": 1.0,
        "low_data_teams": [],
        "convergencia": {
            "success": True, "n_iter": 50, "message": "ok", "neg_log_lik": 100.0,
        },
    }
    doc.update(overrides)
    return doc


def write_params(tmp_path: Path, **overrides) -> Path:
    """Persiste el JSON sintetico en tmp_path (crea el directorio si no existe)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "dixon_coles_params.json"
    path.write_text(json.dumps(_make_params_doc(**overrides)), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# R7 — salida humana
# ---------------------------------------------------------------------------


def test_markets_salida_humana(tmp_path: Path, capsys) -> None:
    """R7: markets MEX RSA produce salida humana con porcentajes a 1 decimal."""
    params_path = write_params(tmp_path)
    exit_code = cli.main(["markets", "MEX", "RSA", "--params", str(params_path)])

    assert exit_code == 0, f"exit_code esperado 0, obtenido {exit_code}"
    out = capsys.readouterr().out

    # Debe haber lineas con porcentajes al 1 decimal
    import re
    pct_pattern = re.compile(r"\d+\.\d+%")
    assert pct_pattern.search(out), f"No se encontraron porcentajes en la salida: {out!r}"

    # Palabras clave esperadas en la salida humana
    assert "MEX" in out, "Falta MEX en la salida"
    assert "RSA" in out, "Falta RSA en la salida"
    assert "Over/Under" in out or "over" in out.lower(), "Falta seccion Over/Under"
    assert "BTTS" in out or "btts" in out.lower(), "Falta seccion BTTS"


# ---------------------------------------------------------------------------
# R7 — salida JSON parseable
# ---------------------------------------------------------------------------


def test_markets_json(tmp_path: Path, capsys) -> None:
    """R7: markets MEX RSA --json produce un JSON valido y parseable."""
    params_path = write_params(tmp_path)
    exit_code = cli.main(["markets", "MEX", "RSA", "--json", "--params", str(params_path)])

    assert exit_code == 0, f"exit_code esperado 0, obtenido {exit_code}"
    out = capsys.readouterr().out.strip()

    # Debe ser JSON valido
    try:
        doc = json.loads(out)
    except json.JSONDecodeError as exc:
        pytest.fail(f"La salida no es JSON valido: {exc}\nSalida: {out!r}")

    # Claves obligatorias
    assert "home_code" in doc
    assert "away_code" in doc
    assert "probs" in doc
    assert "totals" in doc
    assert "btts" in doc
    assert "home_totals" in doc
    assert "away_totals" in doc

    assert doc["home_code"] == "MEX"
    assert doc["away_code"] == "RSA"

    # probs suman ~1
    probs = doc["probs"]
    total = probs["home"] + probs["draw"] + probs["away"]
    assert abs(total - 1.0) < 1e-9, f"probs no suman 1: {total}"

    # totals tienen over + under = 1
    for entry in doc["totals"]:
        assert abs(entry["over"] + entry["under"] - 1.0) < 1e-9

    # btts suma 1
    assert abs(doc["btts"]["yes"] + doc["btts"]["no"] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# R7 — lineas custom con --lines
# ---------------------------------------------------------------------------


def test_markets_lines_custom(tmp_path: Path, capsys) -> None:
    """R7: --lines 0.5,2.5 usa lineas custom en el mercado de totales."""
    params_path = write_params(tmp_path)
    exit_code = cli.main([
        "markets", "MEX", "RSA",
        "--json",
        "--lines", "0.5,2.5",
        "--params", str(params_path),
    ])
    assert exit_code == 0
    doc = json.loads(capsys.readouterr().out.strip())

    lines_returned = [e["line"] for e in doc["totals"]]
    assert sorted(lines_returned) == [0.5, 2.5], (
        f"Se esperaban lineas [0.5, 2.5], se obtuvo {lines_returned}"
    )


# ---------------------------------------------------------------------------
# R7 — errores y exit codes
# ---------------------------------------------------------------------------


def test_markets_errores_y_exit_codes(tmp_path: Path, capsys) -> None:
    """R7: errores producen los exit codes correctos y mensajes accionables."""
    # Params ausentes -> exit 1 con mensaje 'train'
    no_params = str(tmp_path / "no_existe.json")
    exit_code = cli.main(["markets", "MEX", "RSA", "--params", no_params])
    assert exit_code == 1, f"Exit code esperado 1 (params ausentes), obtenido {exit_code}"
    err = capsys.readouterr().err
    assert "train" in err, f"Falta 'train' en stderr: {err!r}"

    # Equipo desconocido en params -> exit 1
    params_without_rsa = write_params(tmp_path / "sub", **{
        "attack": {"MEX": 0.20, "ARG": 0.40},
        "defense": {"MEX": 0.05, "ARG": 0.30},
    })
    exit_code2 = cli.main(["markets", "MEX", "RSA", "--params", str(params_without_rsa)])
    assert exit_code2 == 1, f"Exit code esperado 1 (equipo desconocido), obtenido {exit_code2}"
    err2 = capsys.readouterr().err
    assert "error:" in err2.lower(), f"Falta 'error:' en stderr: {err2!r}"

    # Codigo invalido -> exit 1
    exit_code3 = cli.main(["markets", "INVALIDO", "RSA", "--params", str(write_params(tmp_path))])
    assert exit_code3 == 1

    # HOME == AWAY -> exit 1
    params_path = write_params(tmp_path)
    exit_code4 = cli.main(["markets", "MEX", "MEX", "--params", str(params_path)])
    assert exit_code4 == 1

    # Linea invalida en --lines: argparse llama _parse_lines_arg que lanza ValueError
    # argparse convierte eso a SystemExit(2)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["markets", "MEX", "RSA", "--lines", "1.0,2.0", "--params", str(params_path)])
    assert exc_info.value.code == 2, (
        f"Exit code esperado 2 para linea invalida, obtenido {exc_info.value.code}"
    )

    # Exito -> exit 0
    exit_ok = cli.main(["markets", "MEX", "RSA", "--params", str(params_path)])
    assert exit_ok == 0


# ---------------------------------------------------------------------------
# R7 — subcomandos previos intactos
# ---------------------------------------------------------------------------


def test_subcomandos_previos_intactos(tmp_path: Path, capsys, monkeypatch) -> None:
    """R7: los subcomandos previos (predict, schedule) siguen funcionando igual."""
    # predict con params sinteticos
    params_path = write_params(tmp_path)
    exit_code = cli.main([
        "predict", "MEX", "RSA",
        "--params", str(params_path),
        "--features", str(tmp_path / "no_existe.csv"),
    ])
    assert exit_code == 0, f"predict fallo con exit_code {exit_code}"
    out = capsys.readouterr().out
    assert "MEX" in out and "RSA" in out, "predict no muestra los equipos correctamente"
    assert "%" in out, "predict no muestra porcentajes"

    # schedule sin bronze -> exit 1 con mensaje accionable
    no_bronze = str(tmp_path / "no_bronze.csv")
    exit_sch = cli.main(["schedule", "--results-csv", no_bronze])
    assert exit_sch == 1, f"schedule sin bronze debe ser exit 1, obtenido {exit_sch}"
    err_sch = capsys.readouterr().err
    assert "ingest-public" in err_sch, f"Falta 'ingest-public' en stderr de schedule: {err_sch!r}"
