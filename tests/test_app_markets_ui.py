"""Tests UI de la sub-pestana Mercados con streamlit.testing.v1.AppTest (Feature 4 R8).

Patron de inyeccion de rutas: identico a tests/test_app_ui.py (monkeypatch de
las constantes DEFAULT_* de src/app/data.py y src/app/main.py antes de
AppTest.run()). 100% headless, cero red, cero navegador real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures de datos sinteticos (mismo esquema que test_app_ui.py)
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
    ("JPN", 0, "", "", 1500.0),
    ("MEX", 15, "1.5", "1.1", 1800.0),
    ("USA", 14, "1.4", "1.2", 1750.0),
    ("CAN", 12, "1.3", "1.2", 1700.0),
)

HISTORY_HEADER = "date,code,opponent_code,elo_pre,elo_post,k,g,we,score"
HISTORY_ROWS = (
    "2025-10-01,ARG,BRA,2080.0,2090.0,35.0,1.0,0.55,1.0",
    "2025-10-01,BRA,ARG,2040.0,2030.0,35.0,1.0,0.45,0.0",
    "2025-10-05,MEX,USA,1790.0,1800.0,35.0,1.0,0.5,1.0",
    "2025-11-01,ARG,MEX,2090.0,2100.0,35.0,1.0,0.6,1.0",
)

RESULTS_HEADER = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral"

# Partido pendiente predecible (MEX y ARG estan en los params sinteticos)
RESULTS_ROWS_PREDECIBLE: tuple[str, ...] = (
    "2026-06-11,Mexico,Argentina,NA,NA,FIFA World Cup,Mexico City,Mexico,FALSE",
)

# Partido con equipo sin alias FIFA (no predecible)
RESULTS_ROWS_NO_PREDECIBLE: tuple[str, ...] = (
    "2026-06-11,Atlantis FC,Argentina,NA,NA,FIFA World Cup,Nowhere,NA,FALSE",
)


def make_params(success: bool = True) -> dict:
    """Parametros Dixon-Coles sinteticos con MEX y ARG."""
    return {
        "as_of_date": AS_OF,
        "from_date": "2018-01-01",
        "xi": 0.65,
        "mu": 0.1,
        "home_advantage": 0.3,
        "rho": -0.08,
        "attack": {
            "ARG": 0.40, "BRA": 0.15, "FRA": 0.25, "JPN": -0.30,
            "MEX": 0.20, "USA": 0.10, "CAN": 0.05, "andorra": -0.80,
        },
        "defense": {
            "ARG": 0.30, "BRA": 0.20, "FRA": 0.10, "JPN": -0.40,
            "MEX": 0.05, "USA": 0.00, "CAN": -0.05, "andorra": -0.60,
        },
        "n_matches": 240,
        "n_teams": 7,
        "min_matches": 5,
        "reg_lambda": 1.0,
        "low_data_teams": ["andorra"],
        "convergencia": {
            "success": success, "n_iter": 57, "message": "ok", "neg_log_lik": 100.0
        },
    }


def write_inputs(
    base: Path,
    *,
    success: bool = True,
    results_rows: tuple[str, ...] | None = None,
    with_results: bool = True,
) -> dict[str, Path]:
    """Crea insumos sinteticos en base (layout real data/gold, data/bronze)."""
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
    params_path.write_text(json.dumps(make_params(success)), encoding="utf-8")

    results = base / "data" / "bronze" / "public_results" / "results.csv"
    if with_results:
        results.parent.mkdir(parents=True, exist_ok=True)
        rows = RESULTS_ROWS_PREDECIBLE if results_rows is None else results_rows
        results.write_text("\n".join([RESULTS_HEADER, *rows]) + "\n", encoding="utf-8")

    return {
        "features": features,
        "history": history,
        "params": params_path,
        "results": results,
    }


def _patch_defaults(monkeypatch, paths: dict[str, Path]) -> None:
    """Inyecta rutas sinteticas en src.app.data y src.app.main antes de AppTest.run().

    Args:
        monkeypatch: Fixture de pytest.
        paths: Dict con claves 'features', 'history', 'params', 'results'.
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


def _get_app(monkeypatch, paths: dict[str, Path], *, timeout: float = 10.0):
    """Crea y ejecuta un AppTest con rutas inyectadas.

    Args:
        monkeypatch: Fixture de pytest.
        paths: Rutas sinteticas.
        timeout: Tiempo maximo de run.

    Returns:
        AppTest ejecutado.
    """
    from streamlit.testing.v1 import AppTest

    # Limpiar caches entre tests
    import src.app.main as main_mod
    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()

    # Limpiar cache de mercados
    from src.app.tabs.calendario import _cached_market_summary
    _cached_market_summary.clear()

    _patch_defaults(monkeypatch, paths)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=timeout)
    at.run()
    return at


# ---------------------------------------------------------------------------
# R8 — sub-pestana Mercados presente en partido predecible
# ---------------------------------------------------------------------------


def test_sub_pestana_mercados_presente(tmp_path: Path, monkeypatch) -> None:
    """R8: partido predecible seleccionado -> sub-pestana 'Mercados' presente con porcentajes."""
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod
    from src.app.tabs.calendario import _cached_market_summary

    # Limpiar caches
    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()
    _cached_market_summary.clear()

    paths = write_inputs(tmp_path)
    _patch_defaults(monkeypatch, paths)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=10.0)

    # Inyectar selected_match para ver el detalle
    at.session_state["selected_match"] = ("2026-06-11", "Mexico", "Argentina")
    at.run()

    assert not at.exception, f"AppTest exception: {at.exception}"

    # La sub-pestana Mercados debe aparecer en las tabs
    all_tabs = at.tabs
    tab_labels = [t.label for t in all_tabs]
    labels_str = " ".join(tab_labels)

    assert "Mercados" in labels_str, (
        f"Sub-pestana 'Mercados' no encontrada. Tabs: {tab_labels!r}"
    )

    # Debe haber porcentajes a 1 decimal en el contenido de la app
    # AppTest expone st.write como at.markdown o at.text segun el tipo
    import re
    all_writes = [str(w.value) for w in at.markdown] + [str(w.value) for w in at.text]
    all_text = " ".join(all_writes)
    pct_pattern = re.compile(r"\d+\.\d+%")
    assert pct_pattern.search(all_text), (
        f"No se encontraron porcentajes con formato .1f% en la UI. "
        f"Contenido: {all_text[:500]!r}"
    )

    # Palabras clave de mercados deben estar presentes
    assert (
        "Over/Under" in all_text
        or "over" in all_text.lower()
        or "BTTS" in all_text
        or "btts" in all_text.lower()
    ), (
        f"Falta contenido de mercados (Over/Under, BTTS) en la UI. "
        f"Contenido: {all_text[:500]!r}"
    )


# ---------------------------------------------------------------------------
# R8 — sub-pestana Mercados ausente si no predecible
# ---------------------------------------------------------------------------


def test_sub_pestana_ausente_si_no_predecible(tmp_path: Path, monkeypatch) -> None:
    """R8: partido no predecible -> sub-pestana 'Mercados' NO aparece en el detalle."""
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod
    from src.app.tabs.calendario import _cached_market_summary

    # Limpiar caches
    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()
    _cached_market_summary.clear()

    paths = write_inputs(tmp_path, results_rows=RESULTS_ROWS_NO_PREDECIBLE)
    _patch_defaults(monkeypatch, paths)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=10.0)

    # Inyectar selected_match con el partido no predecible
    at.session_state["selected_match"] = ("2026-06-11", "Atlantis FC", "Argentina")
    at.run()

    assert not at.exception, f"AppTest exception inesperada: {at.exception}"

    # La sub-pestana Mercados NO debe aparecer
    all_tabs = at.tabs
    tab_labels = [t.label for t in all_tabs]
    labels_str = " ".join(tab_labels)

    assert "Mercados" not in labels_str, (
        f"Sub-pestana 'Mercados' aparecio para partido no predecible. "
        f"Tabs: {tab_labels!r}"
    )
