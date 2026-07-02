"""Feature 5 — Seccion Backtest en la pestana Modelo (R11).

Tests con AppTest (patron de tests/test_app_ui.py). Verifica:
- test_seccion_backtest_con_summary: si existe summary.json, muestra metricas.
- test_seccion_backtest_sin_summary: si no existe, muestra el caption con el comando.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers compartidos con test_app_ui.py (copiados para independencia)
# ---------------------------------------------------------------------------

AS_OF = "2025-12-01"

FEATURES_HEADER = (
    "code,as_of_date,matches_count,gf_ma15,ga_ma15,corners_for_ma15,"
    "corners_against_ma15,cards_ma15,shots_ma15,shots_on_target_ma15,"
    "possession_ma15,elo"
)

FEATURES_ROWS = (
    ("ARG", 15, "2.1", "0.8", 2100.0),
    ("BRA", 15, "1.9", "0.9", 2050.0),
    ("FRA", 12, "1.8", "1.0", 2000.0),
    ("MEX", 15, "1.5", "1.1", 1800.0),
    ("USA", 14, "1.4", "1.2", 1750.0),
)

HISTORY_HEADER = "date,code,opponent_code,elo_pre,elo_post,k,g,we,score"
HISTORY_ROWS = (
    "2025-10-01,ARG,BRA,2080.0,2090.0,35.0,1.0,0.55,1.0",
    "2025-10-01,BRA,ARG,2040.0,2030.0,35.0,1.0,0.45,0.0",
    "2025-11-01,ARG,MEX,2090.0,2100.0,35.0,1.0,0.6,1.0",
)

RESULTS_HEADER = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral"
RESULTS_ROWS = (
    "2025-06-11,Mexico,Argentina,NA,NA,FIFA World Cup,Mexico City,Mexico,FALSE",
)


def _make_params(success: bool = True) -> dict:
    return {
        "as_of_date": AS_OF,
        "from_date": "2018-01-01",
        "xi": 0.65,
        "mu": 0.1,
        "home_advantage": 0.3,
        "rho": -0.08,
        "attack": {
            "ARG": 0.40, "BRA": 0.15, "FRA": 0.25, "MEX": 0.20, "USA": 0.10,
        },
        "defense": {
            "ARG": 0.30, "BRA": 0.20, "FRA": 0.10, "MEX": 0.05, "USA": 0.00,
        },
        "n_matches": 240,
        "n_teams": 5,
        "min_matches": 5,
        "reg_lambda": 1.0,
        "low_data_teams": [],
        "convergencia": {
            "success": success, "n_iter": 57, "message": "ok", "neg_log_lik": 100.0
        },
    }


def _make_summary(as_of: str = "2024-06-01", n_matches: int = 120) -> dict:
    """Crea un summary.json sintetico de backtest.

    Args:
        as_of: Effective to_date of the backtest.
        n_matches: Number of evaluated matches.

    Returns:
        Summary dict as it would be written by write_report.
    """
    return {
        "as_of": as_of,
        "config": {
            "bins": 10,
            "from_date": "2024-01-01",
            "min_matches": 5,
            "odds_csv": None,
            "out_dir": "data/reports/backtest",
            "refit_every": "month",
            "reg_lambda": 1.0,
            "silver_path": "data/silver/matches.csv",
            "to_date": None,
            "value_threshold": 0.05,
            "xi": 0.65,
        },
        "low_data": {
            "low_data_en_torneo": False,
            "teams": [],
        },
        "metrics": {
            "marginal": {
                "accuracy": 0.350000,
                "brier": 0.650000,
                "log_loss": 1.050000,
                "n_matches": n_matches,
                "n_skipped": 5,
            },
            "model": {
                "accuracy": 0.420000,
                "brier": 0.580000,
                "log_loss": 0.980000,
                "n_matches": n_matches,
                "n_skipped": 5,
            },
            "uniform": {
                "accuracy": 0.330000,
                "brier": 0.666667,
                "log_loss": 1.098612,
                "n_matches": n_matches,
                "n_skipped": 5,
            },
        },
        "n_windows": 6,
    }


def _write_base_inputs(base: Path, *, with_summary: bool = False) -> dict[str, Path]:
    """Crea los insumos base de la app en base/.

    Args:
        base: Base directory for synthetic data.
        with_summary: If True, write a synthetic summary.json.

    Returns:
        Dict with paths to all created files.
    """
    gold = base / "data" / "gold"
    gold.mkdir(parents=True, exist_ok=True)

    features = gold / "team_features.csv"
    features.write_text(
        "\n".join(
            [FEATURES_HEADER]
            + [f"{c},{AS_OF},{m},{gf},{ga},,,,,,,{elo}" for c, m, gf, ga, elo in FEATURES_ROWS]
        )
        + "\n",
        encoding="utf-8",
    )

    history = gold / "elo_history.csv"
    history.write_text("\n".join([HISTORY_HEADER, *HISTORY_ROWS]) + "\n", encoding="utf-8")

    params_path = gold / "dixon_coles_params.json"
    params_path.write_text(json.dumps(_make_params()), encoding="utf-8")

    results = base / "data" / "bronze" / "public_results" / "results.csv"
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text("\n".join([RESULTS_HEADER, *RESULTS_ROWS]) + "\n", encoding="utf-8")

    paths = {
        "features": features,
        "history": history,
        "params": params_path,
        "results": results,
    }

    if with_summary:
        backtest_dir = base / "data" / "reports" / "backtest"
        backtest_dir.mkdir(parents=True, exist_ok=True)
        summary_path = backtest_dir / "summary.json"
        summary_path.write_text(
            json.dumps(_make_summary(), sort_keys=True, indent=2),
            encoding="utf-8",
        )
        paths["summary"] = summary_path

    return paths


def _patch_app_defaults(monkeypatch, paths: dict[str, Path]) -> None:
    """Inyecta rutas sinteticas en src.app.data y src.app.main.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        paths: Dict with synthetic file paths.
    """
    import src.app.data as data_mod
    import src.app.main as main_mod

    monkeypatch.setattr(data_mod, "DEFAULT_FEATURES_CSV", paths["features"])
    monkeypatch.setattr(data_mod, "DEFAULT_ELO_HISTORY_CSV", paths["history"])
    monkeypatch.setattr(data_mod, "DEFAULT_PARAMS_PATH", paths["params"])
    monkeypatch.setattr(data_mod, "DEFAULT_RESULTS_CSV", paths["results"])

    monkeypatch.setattr(main_mod, "DEFAULT_FEATURES_CSV", paths["features"])
    monkeypatch.setattr(main_mod, "DEFAULT_ELO_HISTORY_CSV", paths["history"])
    monkeypatch.setattr(main_mod, "DEFAULT_PARAMS_PATH", paths["params"])
    monkeypatch.setattr(main_mod, "DEFAULT_RESULTS_CSV", paths["results"])


def _run_app(monkeypatch, paths: dict[str, Path], *, summary_path: Path | None = None):
    """Ejecuta AppTest con rutas inyectadas y summary opcional.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        paths: Base app file paths.
        summary_path: If provided, inject as DEFAULT_BACKTEST_SUMMARY in modelo.py.

    Returns:
        Executed AppTest instance.
    """
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod
    import src.app.tabs.modelo as modelo_mod

    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()

    _patch_app_defaults(monkeypatch, paths)

    if summary_path is not None:
        monkeypatch.setattr(modelo_mod, "DEFAULT_BACKTEST_SUMMARY", summary_path)
    else:
        # Apuntar a una ruta inexistente para simular "no hay reporte"
        monkeypatch.setattr(
            modelo_mod, "DEFAULT_BACKTEST_SUMMARY",
            paths["features"].parent / "NO_EXISTE_summary.json"
        )

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=15.0)
    at.run()
    return at


# ---------------------------------------------------------------------------
# R11 — test_seccion_backtest_con_summary
# ---------------------------------------------------------------------------


def test_seccion_backtest_con_summary(tmp_path, monkeypatch):
    """R11: si existe summary.json, la seccion Backtest muestra metricas clave."""
    paths = _write_base_inputs(tmp_path, with_summary=True)
    summary_path = paths["summary"]

    at = _run_app(monkeypatch, paths, summary_path=summary_path)

    assert not at.exception, f"AppTest exception: {at.exception}"

    # La seccion Backtest debe mostrar algun metrico
    # Buscamos en metricas (st.metric) si hay algun valor de log-loss o Brier
    all_metrics = at.metric
    metric_labels = [str(m.label) for m in all_metrics]
    metric_values = [str(m.value) for m in all_metrics]

    # Al menos un metric con label que mencione log-loss o Brier o Exactitud
    backtest_labels = [
        l for l in metric_labels
        if any(kw in l.lower() for kw in ("log", "brier", "exactitud", "backtest"))
    ]
    assert len(backtest_labels) >= 1, (
        f"No se encontro ninguna metrica de backtest en: {metric_labels}"
    )

    # Verificar que no hay excepcion
    assert not at.exception


# ---------------------------------------------------------------------------
# R11 — test_seccion_backtest_sin_summary
# ---------------------------------------------------------------------------


def test_seccion_backtest_sin_summary(tmp_path, monkeypatch):
    """R11: si no existe summary.json, muestra el caption con el comando CLI."""
    paths = _write_base_inputs(tmp_path, with_summary=False)

    at = _run_app(monkeypatch, paths, summary_path=None)

    assert not at.exception, f"AppTest exception: {at.exception}"

    # Debe aparecer algun caption o texto con el comando
    all_captions = [str(c.value) for c in at.caption]
    all_text = " ".join(all_captions)

    # El caption debe mencionar el comando de backtest
    assert "backtest" in all_text.lower(), (
        f"El caption no menciona 'backtest': {all_captions}"
    )
