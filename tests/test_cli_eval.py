"""Feature 10 — registro_y_evaluacion: tests CLI predict-log y evaluate (R12, R13).

100 % offline y deterministas: se usan monkeypatches sobre ``src.cli`` para aislar
``log_predictions`` y ``evaluate`` de la capa real. Los tests de subcomandos exactos
no usan mocks: verifican el conjunto directo desde ``build_parser``.

Trazabilidad:
    R12 → test_predict_log_exito
    R12 → test_subcomandos_exactos_intactos
    R12 → test_predict_log_exit_codes
    R13 → test_evaluate_exito_y_reporte
    R13 → test_evaluate_sin_log_error
    R13 → test_evaluate_sin_evaluables_exit0
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.cli as cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AS_OF = "2026-06-11"
TIMESTAMP = "2026-06-11T10:00:00Z"

# Conjunto EXACTO de subcomandos esperados (R12 + R7 feature 11 + R8 feature 13 + R4 feature 24 + R3 feature 25)
EXPECTED_SUBCOMMANDS = {
    "ingest-public",
    "build-features",
    "train",
    "predict",
    "schedule",
    "markets",
    "backtest",
    "predict-log",
    "evaluate",
    "ingest-goalscorers",  # Feature 11
    "scorers",             # Feature 11
    "simulate",            # Feature 13
    "ingest-elo",          # Feature 14
    "ingest-wiki-stats",    # Feature 15
    "ingest-roster",        # Feature 21
    "ingest-fotmob-stats",  # Feature 23
    "corners",              # Feature 24
    "count-market",         # Feature 25
    "ingest-ko",            # Feature 27
    "build-ko-fixtures",    # Feature 27
    "ingest-lineups",       # Feature 28
    "build-lineup-strength",# Feature 28
}


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Ejecuta ``main(argv)`` y captura stdout/stderr vía capsys."""
    import io, sys
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out_buf, err_buf
    try:
        code = cli.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return code, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# R12 — test_subcomandos_exactos_intactos
# ---------------------------------------------------------------------------


def test_subcomandos_exactos_intactos():
    """R12/R7: el conjunto EXACTO de subcomandos es {ingest-public, build-features, train,
    predict, schedule, markets, backtest, predict-log, evaluate, ingest-goalscorers, scorers,
    simulate, ingest-elo}.
    Los 12 previos están intactos; feature 14 añade exactamente 1 nuevo (ingest-elo, R8 f14).
    """
    parser = cli.build_parser()
    # El atributo _subparsers._group_actions contiene los subparsers
    subparsers_action = None
    for action in parser._subparsers._group_actions:
        if hasattr(action, "choices") and action.choices:
            subparsers_action = action
            break

    assert subparsers_action is not None, "No se encontraron subparsers en el parser"
    actual_subcommands = set(subparsers_action.choices.keys())

    assert actual_subcommands == EXPECTED_SUBCOMMANDS, (
        f"Conjunto de subcomandos incorrecto.\n"
        f"Esperados: {sorted(EXPECTED_SUBCOMMANDS)}\n"
        f"Obtenidos: {sorted(actual_subcommands)}\n"
        f"Adicionales: {sorted(actual_subcommands - EXPECTED_SUBCOMMANDS)}\n"
        f"Faltantes:   {sorted(EXPECTED_SUBCOMMANDS - actual_subcommands)}"
    )


def test_subcomandos_previos_siguen_funcionando():
    """R12: los 7 subcomandos previos siguen resolviendo a sus funciones correctas."""
    parser = cli.build_parser()
    subparsers_action = None
    for action in parser._subparsers._group_actions:
        if hasattr(action, "choices") and action.choices:
            subparsers_action = action
            break

    expected_funcs = {
        "ingest-public": cli.cmd_ingest_public,
        "build-features": cli.cmd_build_features,
        "train": cli.cmd_train,
        "predict": cli.cmd_predict,
        "schedule": cli.cmd_schedule,
        "markets": cli.cmd_markets,
        "backtest": cli.cmd_backtest,
    }

    for subcommand, expected_func in expected_funcs.items():
        subparser = subparsers_action.choices[subcommand]
        # Parsear con args mínimos para verificar el set_defaults(func=...)
        # Solo verificamos que el subcomando existe y tiene el func correcto
        # (sin ejecutar realmente)
        import argparse
        namespace = argparse.Namespace()
        # El defaults se establece via set_defaults, accesible en _defaults
        assert subparser.get_default("func") == expected_func, (
            f"Subcomando '{subcommand}' no apunta a la función correcta"
        )


# ---------------------------------------------------------------------------
# R12 — test_predict_log_exito
# ---------------------------------------------------------------------------


def test_predict_log_exito(tmp_path, monkeypatch):
    """R12: predict-log con éxito → exit 0 y mensaje ✅."""
    # Fixture: CSV de targets en tmp_path
    targets_csv = tmp_path / "fixtures.csv"
    targets_csv.write_text(
        "date,match_id,home_code,away_code,neutral\n"
        "2026-06-15,m1,ARG,BRA,False\n",
        encoding="utf-8",
    )

    # Monkeypatch log_predictions en el módulo cmd_predict_log importa
    import src.eval.prediction_log as pl_module

    def fake_log_predictions(**kwargs):
        return {"n_logged": 1, "n_skipped": 0, "skipped": []}

    monkeypatch.setattr(pl_module, "log_predictions", fake_log_predictions)
    monkeypatch.setattr(pl_module, "fixtures_from_csv", lambda p: [
        {"date": "2026-06-15", "match_id": "m1", "home_code": "ARG", "away_code": "BRA", "neutral": False}
    ])

    log_out = tmp_path / "data" / "predictions" / "log.csv"
    code, out, err = _run([
        "predict-log",
        "--as-of", AS_OF,
        "--timestamp", TIMESTAMP,
        "--targets", str(targets_csv),
        "--out", str(log_out),
    ])

    assert code == 0, f"Se esperaba exit 0, se obtuvo {code}\nstderr: {err}"
    assert "predict-log" in out or "predicciones" in out.lower(), (
        f"Mensaje de éxito esperado en stdout:\n{out}"
    )


def test_predict_log_targets_schedule(tmp_path, monkeypatch):
    """R12: --targets schedule usa fixtures_from_schedule."""
    import src.eval.prediction_log as pl_module

    called_with_schedule = []

    def fake_from_schedule(results_csv):
        called_with_schedule.append(results_csv)
        return []

    def fake_log_predictions(**kwargs):
        return {"n_logged": 0, "n_skipped": 0, "skipped": []}

    monkeypatch.setattr(pl_module, "fixtures_from_schedule", fake_from_schedule)
    monkeypatch.setattr(pl_module, "log_predictions", fake_log_predictions)

    results_csv = tmp_path / "results.csv"
    results_csv.write_text("date,home_team,away_team,home_score,away_score,tournament\n", encoding="utf-8")

    code, out, _ = _run([
        "predict-log",
        "--as-of", AS_OF,
        "--timestamp", TIMESTAMP,
        "--targets", "schedule",
        "--results-csv", str(results_csv),
        "--out", str(tmp_path / "log.csv"),
    ])
    assert code == 0
    assert len(called_with_schedule) == 1  # se llamó a fixtures_from_schedule


# ---------------------------------------------------------------------------
# R12 — test_predict_log_exit_codes
# ---------------------------------------------------------------------------


def test_predict_log_exit_codes(tmp_path, monkeypatch):
    """R12: exit 1 cuando el CSV de targets no existe."""
    code, out, err = _run([
        "predict-log",
        "--as-of", AS_OF,
        "--timestamp", TIMESTAMP,
        "--targets", str(tmp_path / "no_existe.csv"),
        "--out", str(tmp_path / "log.csv"),
    ])
    assert code == 1, f"Se esperaba exit 1 (targets no existe), se obtuvo {code}"
    assert "error" in err.lower(), f"Mensaje de error esperado en stderr:\n{err}"


def test_predict_log_exit_code_0_sin_fixtures(tmp_path, monkeypatch):
    """R12: exit 0 cuando no hay fixtures objetivo."""
    import src.eval.prediction_log as pl_module

    monkeypatch.setattr(pl_module, "fixtures_from_schedule", lambda _: [])

    # results_csv debe existir para no fallar en FileNotFoundError del schedule
    results_csv = tmp_path / "results.csv"
    results_csv.write_text("date,home_team,away_team,home_score,away_score,tournament\n", encoding="utf-8")

    code, out, err = _run([
        "predict-log",
        "--as-of", AS_OF,
        "--timestamp", TIMESTAMP,
        "--targets", "schedule",
        "--results-csv", str(results_csv),
        "--out", str(tmp_path / "log.csv"),
    ])
    assert code == 0, f"Se esperaba exit 0 (sin fixtures), se obtuvo {code}\n{err}"


def test_predict_log_error_silver_no_existe(tmp_path, monkeypatch):
    """R12: exit 1 cuando el silver no existe."""
    targets_csv = tmp_path / "fixtures.csv"
    targets_csv.write_text(
        "date,match_id,home_code,away_code,neutral\n"
        "2026-06-15,m1,ARG,BRA,False\n",
        encoding="utf-8",
    )

    import src.eval.prediction_log as pl_module

    def fake_log_pred(**kwargs):
        raise FileNotFoundError("No existe el silver: /no/existe")

    monkeypatch.setattr(pl_module, "log_predictions", fake_log_pred)
    monkeypatch.setattr(pl_module, "fixtures_from_csv", lambda p: [
        {"date": "2026-06-15", "match_id": "m1", "home_code": "ARG", "away_code": "BRA", "neutral": False}
    ])

    code, _, err = _run([
        "predict-log",
        "--as-of", AS_OF,
        "--timestamp", TIMESTAMP,
        "--targets", str(targets_csv),
        "--out", str(tmp_path / "log.csv"),
    ])
    assert code == 1, f"Se esperaba exit 1 (silver no existe), se obtuvo {code}"


# ---------------------------------------------------------------------------
# R13 — test_evaluate_exito_y_reporte
# ---------------------------------------------------------------------------


def test_evaluate_exito_y_reporte(tmp_path, monkeypatch):
    """R13: evaluate con éxito → exit 0, tabla en stdout, reporte escrito."""
    import src.eval.evaluate as ev_module

    fake_result = {
        "n_evaluable": 5,
        "n_skipped": 1,
        "metrics": {"log_loss": 1.05, "brier": 0.38, "accuracy": 0.60,
                    "n_matches": 5, "n_skipped": 1},
        "lambda_error": {"rmse": 0.45, "mae": 0.30, "n": 10},
        "market_metrics": None,
        "report": {"summary_path": str(tmp_path / "summary.json")},
        "all_skipped": False,
    }

    monkeypatch.setattr(ev_module, "evaluate", lambda **kwargs: fake_result)

    log_path = tmp_path / "log.csv"
    log_path.write_text("x\n", encoding="utf-8")  # archivo existe (no se usa realmente)
    silver_path = tmp_path / "silver.csv"
    silver_path.write_text("x\n", encoding="utf-8")

    code, out, err = _run([
        "evaluate",
        "--log", str(log_path),
        "--silver", str(silver_path),
        "--out", str(tmp_path / "data" / "reports" / "evaluacion"),
    ])

    assert code == 0, f"Se esperaba exit 0, se obtuvo {code}\nstderr: {err}"
    assert "log-loss" in out.lower() or "logloss" in out.lower() or "1.0500" in out or "Métrica" in out, (
        f"Tabla de métricas esperada en stdout:\n{out}"
    )


def test_evaluate_con_markets(tmp_path, monkeypatch):
    """R13: evaluate --markets muestra métricas de mercado."""
    import src.eval.evaluate as ev_module

    fake_result = {
        "n_evaluable": 3,
        "n_skipped": 0,
        "metrics": {"log_loss": 1.1, "brier": 0.40, "accuracy": 0.55,
                    "n_matches": 3, "n_skipped": 0},
        "lambda_error": {"rmse": 0.50, "mae": 0.35, "n": 6},
        "market_metrics": {"brier_over25": 0.22, "brier_btts": 0.18, "n": 3},
        "report": {},
        "all_skipped": False,
    }
    monkeypatch.setattr(ev_module, "evaluate", lambda **kwargs: fake_result)

    log_path = tmp_path / "log.csv"
    log_path.write_text("x\n", encoding="utf-8")
    silver_path = tmp_path / "silver.csv"
    silver_path.write_text("x\n", encoding="utf-8")

    code, out, _ = _run([
        "evaluate",
        "--log", str(log_path),
        "--silver", str(silver_path),
        "--markets",
    ])
    assert code == 0
    assert "0.22" in out or "brier" in out.lower() or "mercados" in out.lower(), (
        f"Métricas de mercado esperadas en stdout:\n{out}"
    )


# ---------------------------------------------------------------------------
# R13 — test_evaluate_sin_log_error
# ---------------------------------------------------------------------------


def test_evaluate_sin_log_error(tmp_path):
    """R13: evaluate con log inexistente → exit 1 con mensaje accionable."""
    code, out, err = _run([
        "evaluate",
        "--log", str(tmp_path / "no_existe_log.csv"),
    ])
    assert code == 1, f"Se esperaba exit 1 (log no existe), se obtuvo {code}"
    assert "error" in err.lower(), f"Mensaje de error en stderr esperado:\n{err}"
    # El mensaje debe mencionar qué hacer
    assert "predict-log" in err or "predicciones" in err.lower(), (
        f"El error debe mencionar 'predict-log' como acción:\n{err}"
    )


# ---------------------------------------------------------------------------
# R13 — test_evaluate_sin_evaluables_exit0
# ---------------------------------------------------------------------------


def test_evaluate_sin_evaluables_exit0(tmp_path, monkeypatch):
    """R13: todos skipped (sin marcadores reales) → exit 0 con mensaje claro."""
    import src.eval.evaluate as ev_module

    fake_result = {
        "n_evaluable": 0,
        "n_skipped": 5,
        "metrics": None,
        "lambda_error": None,
        "market_metrics": None,
        "all_skipped": True,
    }
    monkeypatch.setattr(ev_module, "evaluate", lambda **kwargs: fake_result)

    log_path = tmp_path / "log.csv"
    log_path.write_text("x\n", encoding="utf-8")
    silver_path = tmp_path / "silver.csv"
    silver_path.write_text("x\n", encoding="utf-8")

    code, out, err = _run([
        "evaluate",
        "--log", str(log_path),
        "--silver", str(silver_path),
    ])

    assert code == 0, f"Se esperaba exit 0 (sin evaluables), se obtuvo {code}"
    # Debe imprimir mensaje claro (no error)
    assert "pendientes" in out.lower() or "0 partidos" in out or "evaluable" in out.lower(), (
        f"Mensaje claro esperado en stdout:\n{out}"
    )
    assert "error" not in err.lower(), f"No debe haber error en stderr:\n{err}"
