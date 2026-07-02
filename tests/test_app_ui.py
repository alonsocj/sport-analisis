"""Tests de UI con streamlit.testing.v1.AppTest (R2, R3, R6–R11, R14, R15).

Cubre EXACTAMENTE los tests asignados a test_app_ui.py en specs/app_streamlit/tasks.md.
100 % headless, cero red, cero navegador real.

Inyeccion de rutas: monkeypatch de las constantes DEFAULT_* de src/app/data.py
(y de src/app/main.py) ANTES de AppTest.run().
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures de datos sinteticos (mismo esquema que test_app_data.py)
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

# 1 jugado (FRA-BRA) + 1 pendiente (MEX-ARG) en dias distintos
RESULTS_ROWS_FULL: tuple[str, ...] = (
    "2026-06-01,France,Brazil,2,1,FIFA World Cup,Paris,France,FALSE",
    "2026-06-11,Mexico,Argentina,NA,NA,FIFA World Cup,Mexico City,Mexico,FALSE",
)

# Solo 1 pendiente para tests de tarjeta
RESULTS_ROWS_PENDIENTE: tuple[str, ...] = (
    "2026-06-11,Mexico,Argentina,NA,NA,FIFA World Cup,Mexico City,Mexico,FALSE",
)


def make_params(success: bool = True) -> dict:
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
        rows = RESULTS_ROWS_FULL if results_rows is None else results_rows
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

    _patch_defaults(monkeypatch, paths)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=timeout)
    at.run()
    return at


# ---------------------------------------------------------------------------
# R14 — tres pestanas con literales constantes
# ---------------------------------------------------------------------------


def test_tres_pestanas_literales(tmp_path: Path, monkeypatch) -> None:
    """R14: la app renderiza exactamente tres pestanas con los literales de main.py."""
    from src.app.main import TAB_CALENDARIO, TAB_MODELO, TAB_SELECCIONES

    paths = write_inputs(tmp_path)
    at = _get_app(monkeypatch, paths)

    assert not at.exception, f"AppTest exception: {at.exception}"
    # Verificar que hay tabs
    assert len(at.tabs) >= 1, "No se encontraron tabs en la app"
    # Las tres etiquetas deben estar presentes
    tab_labels = [t.label for t in at.tabs]
    assert TAB_CALENDARIO in tab_labels, f"Falta {TAB_CALENDARIO!r} en {tab_labels}"
    assert TAB_SELECCIONES in tab_labels, f"Falta {TAB_SELECCIONES!r} en {tab_labels}"
    assert TAB_MODELO in tab_labels, f"Falta {TAB_MODELO!r} en {tab_labels}"


# ---------------------------------------------------------------------------
# R2 — error visible sin pestanas de contenido
# ---------------------------------------------------------------------------


def test_error_visible_sin_pestanas(tmp_path: Path, monkeypatch) -> None:
    """R2: falta gold -> st.error visible; no se renderizan las pestanas de contenido."""
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod
    import src.app.data as data_mod

    # Limpiar cache
    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()

    paths = write_inputs(tmp_path)
    # Eliminar el archivo de features para provocar AppInputError
    paths["features"].unlink()

    _patch_defaults(monkeypatch, paths)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=10.0)
    at.run()

    # Debe haber un error visible (R2)
    assert len(at.error) >= 1, "Se esperaba st.error con mensaje accionable (R2)"
    error_text = " ".join(str(e.value) for e in at.error)
    assert "build-features" in error_text, f"Falta 'build-features' en el error: {error_text!r}"

    # No deben renderizarse las tres pestanas de contenido (R2)
    assert len(at.tabs) == 0, "No deben aparecer pestanas cuando falta gold (R2)"


# ---------------------------------------------------------------------------
# R3 — aviso ingest-public sin bronze
# ---------------------------------------------------------------------------


def test_aviso_ingest_public(tmp_path: Path, monkeypatch) -> None:
    """R3: sin results.csv -> aviso con 'ingest-public' en la pestana Calendario."""
    paths = write_inputs(tmp_path, with_results=False)
    at = _get_app(monkeypatch, paths)

    assert not at.exception, f"AppTest exception: {at.exception}"

    # La app no debe fallar; debe haber aviso en la UI
    # El aviso puede estar como st.warning o st.info
    all_warnings = [str(w.value) for w in at.warning]
    all_infos = [str(i.value) for i in at.info]
    combined = " ".join(all_warnings + all_infos)

    assert "ingest-public" in combined, (
        f"Falta 'ingest-public' en los avisos: warnings={all_warnings!r}, infos={all_infos!r}"
    )


# ---------------------------------------------------------------------------
# R6 — tarjeta de partido pendiente con 1X2
# ---------------------------------------------------------------------------


def test_tarjeta_pendiente_1x2(tmp_path: Path, monkeypatch) -> None:
    """R6: partido pendiente predecible -> probabilidades 1X2 en la tarjeta."""
    paths = write_inputs(tmp_path, results_rows=RESULTS_ROWS_PENDIENTE)
    at = _get_app(monkeypatch, paths)

    assert not at.exception, f"AppTest exception: {at.exception}"

    # Debe haber algun porcentaje con formato .1f%  (R6)
    # Los markdowns incluiran los porcentajes
    all_md = [str(m.value) for m in at.markdown]
    all_text = " ".join(all_md)

    # MEX y ARG deben estar en la UI
    assert "MEX" in all_text or "Mexico" in all_text, (
        f"MEX/Mexico no encontrado en el contenido. Texto: {all_text[:500]!r}"
    )
    # Debe haber algún porcentaje con decimal
    import re
    pct_pattern = re.compile(r"\d+\.\d+%")
    assert pct_pattern.search(all_text), (
        f"No se encontraron probabilidades con formato .1f% en: {all_text[:500]!r}"
    )


# ---------------------------------------------------------------------------
# R7 — disclaimer as_of_date
# ---------------------------------------------------------------------------


def test_disclaimer_as_of_date(tmp_path: Path, monkeypatch) -> None:
    """R7: la pestana Calendario muestra un aviso con as_of_date de los params."""
    paths = write_inputs(tmp_path)
    at = _get_app(monkeypatch, paths)

    assert not at.exception, f"AppTest exception: {at.exception}"

    all_infos = [str(i.value) for i in at.info]
    combined = " ".join(all_infos)

    assert AS_OF in combined, (
        f"as_of_date={AS_OF!r} no encontrado en los st.info: {all_infos!r}"
    )


# ---------------------------------------------------------------------------
# R8 — detalle con sub-pestanas al seleccionar partido
# ---------------------------------------------------------------------------


def test_detalle_sub_pestanas(tmp_path: Path, monkeypatch) -> None:
    """R8: al marcar un partido como selected_match, el detalle renderiza sub-pestanas."""
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod

    # Limpiar cache
    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()

    paths = write_inputs(tmp_path, results_rows=RESULTS_ROWS_PENDIENTE)
    _patch_defaults(monkeypatch, paths)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=10.0)

    # Inyectar selected_match en session_state antes del run
    at.session_state["selected_match"] = ("2026-06-11", "Mexico", "Argentina")
    at.run()

    assert not at.exception, f"AppTest exception: {at.exception}"

    # Deben existir sub-tabs con las etiquetas del detalle
    all_tabs = at.tabs
    tab_labels = [t.label for t in all_tabs]
    labels_str = " ".join(tab_labels)

    # Las sub-pestanas de detalle deben estar presentes
    assert "Predicción" in labels_str or "Predicci" in labels_str, (
        f"Sub-pestana Prediccion no encontrada. Tabs: {tab_labels!r}"
    )
    assert "Equipos" in labels_str, (
        f"Sub-pestana Equipos no encontrada. Tabs: {tab_labels!r}"
    )
    assert "Historial Elo" in labels_str or "Historial" in labels_str, (
        f"Sub-pestana Historial Elo no encontrada. Tabs: {tab_labels!r}"
    )


# ---------------------------------------------------------------------------
# R9 — partido sin prediccion no aborta
# ---------------------------------------------------------------------------


def test_tarjeta_sin_prediccion_no_aborta(tmp_path: Path, monkeypatch) -> None:
    """R9: partido no predecible -> tarjeta con 'sin prediccion'; la app no aborta."""
    # Partido con equipo sin alias FIFA
    rows_con_no_pred = (
        "2026-06-11,Atlantis FC,Argentina,NA,NA,FIFA World Cup,Nowhere,NA,FALSE",
    )
    paths = write_inputs(tmp_path, results_rows=rows_con_no_pred)
    at = _get_app(monkeypatch, paths)

    # La app no debe lanzar excepcion (R9)
    assert not at.exception, f"AppTest exception inesperada: {at.exception}"

    # "sin prediccion" debe aparecer en la UI
    all_captions = [str(c.value) for c in at.caption]
    all_md = [str(m.value) for m in at.markdown]
    combined = " ".join(all_captions + all_md)
    assert "sin predicción" in combined or "sin prediccion" in combined, (
        f"'sin prediccion' no encontrado. captions={all_captions!r}"
    )


# ---------------------------------------------------------------------------
# R10 — ficha de equipo en Selecciones
# ---------------------------------------------------------------------------


def test_ficha_equipo(tmp_path: Path, monkeypatch) -> None:
    """R10: la pestana Selecciones renderiza el ranking y permite seleccionar un equipo."""
    paths = write_inputs(tmp_path)
    at = _get_app(monkeypatch, paths)

    assert not at.exception, f"AppTest exception: {at.exception}"

    # Debe haber un selectbox para elegir equipo (R10)
    assert len(at.selectbox) >= 1, "Se esperaba al menos un st.selectbox en Selecciones"

    # El selectbox debe tener opciones con codigos FIFA
    sb = at.selectbox[0]
    options_str = " ".join(str(o) for o in sb.options)
    assert "ARG" in options_str or "MEX" in options_str, (
        f"Codigos FIFA no encontrados en selectbox options: {options_str[:300]!r}"
    )


# ---------------------------------------------------------------------------
# R11 — metadatos del modelo y aviso de no-convergencia
# ---------------------------------------------------------------------------


def test_metadatos_y_aviso_convergencia(tmp_path: Path, monkeypatch) -> None:
    """R11: pestana Modelo muestra as_of_date; aviso si convergencia.success=False."""
    # ---- caso convergencia OK: no debe haber warning ----
    paths = write_inputs(tmp_path / "conv_ok", success=True)
    at = _get_app(monkeypatch, paths)
    assert not at.exception, f"AppTest exception: {at.exception}"

    # as_of_date debe aparecer en algun metric o texto
    all_metrics = [str(m.value) for m in at.metric]
    combined = " ".join(all_metrics)
    assert AS_OF in combined, (
        f"as_of_date={AS_OF!r} no encontrado en metrics: {all_metrics!r}"
    )

    # ---- caso no convergencia: debe haber st.warning con el aviso ----
    import src.app.main as main_mod
    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()

    paths2 = write_inputs(tmp_path / "conv_fail", success=False)
    _patch_defaults(monkeypatch, paths2)

    from streamlit.testing.v1 import AppTest
    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at2 = AppTest.from_file(str(app_path), default_timeout=10.0)
    at2.run()

    assert not at2.exception, f"AppTest exception: {at2.exception}"
    all_warnings = [str(w.value) for w in at2.warning]
    combined_w = " ".join(all_warnings)
    assert "convergió" in combined_w or "convergencia" in combined_w.lower() or "convergi" in combined_w, (
        f"Aviso de no-convergencia no encontrado en warnings: {all_warnings!r}"
    )


# ---------------------------------------------------------------------------
# R8 (BUG-1) — top-5 marcadores con formato de probabilidad en sub-pestaña Predicción
# ---------------------------------------------------------------------------


def test_detalle_top5_marcadores(tmp_path: Path, monkeypatch) -> None:
    """R8 (BUG-1): sub-pestana Prediccion incluye bloque 'Top-5' con marcadores y probabilidades.

    Este test FALLA si se eliminan las lineas del top-5 en src/app/tabs/calendario.py
    (st.markdown 'Top-5...' + st.write para cada marcador).
    """
    import re
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod

    # Limpiar cache
    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()

    paths = write_inputs(tmp_path, results_rows=RESULTS_ROWS_PENDIENTE)
    _patch_defaults(monkeypatch, paths)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=10.0)

    # Inyectar selected_match en session_state antes del run
    at.session_state["selected_match"] = ("2026-06-11", "Mexico", "Argentina")
    at.run()

    assert not at.exception, f"AppTest exception: {at.exception}"

    # (a) El literal "Top-5" debe estar en algun st.markdown del detalle
    all_md = [str(m.value) for m in at.markdown]
    top5_present = any("Top-5" in md for md in all_md)
    assert top5_present, (
        f"'Top-5' no encontrado en ningun st.markdown. "
        f"Markdowns disponibles: {all_md!r}"
    )

    # (b) Debe existir al menos un marcador con formato "N-N: XX.XX%" en st.write
    # AppTest expone st.write como at.markdown o at.text segun el tipo
    all_write = [str(w.value) for w in at.markdown] + [str(w.value) for w in at.text]
    score_pattern = re.compile(r"\d+–\d+:\s*\d+\.\d+%")  # "0-0: 12.34%"
    marcadores = [w for w in all_write if score_pattern.search(w)]
    assert len(marcadores) >= 1, (
        f"No se encontraron marcadores con formato 'N-N: XX.XX%' en la UI. "
        f"Contenido disponible: {all_write[:20]!r}"
    )


# ---------------------------------------------------------------------------
# R15 — config.toml: telemetria off y address=localhost
# ---------------------------------------------------------------------------


def test_config_toml_telemetria_off_localhost() -> None:
    """R15: .streamlit/config.toml tiene gatherUsageStats=false y address='localhost'."""
    import tomllib

    config_path = Path(__file__).parent.parent / ".streamlit" / "config.toml"
    assert config_path.is_file(), f"No existe .streamlit/config.toml en: {config_path}"

    with config_path.open("rb") as fh:
        config = tomllib.load(fh)

    browser = config.get("browser", {})
    server = config.get("server", {})

    assert browser.get("gatherUsageStats") is False, (
        f"browser.gatherUsageStats debe ser false; config: {browser!r}"
    )
    assert server.get("address") == "localhost", (
        f"server.address debe ser 'localhost'; config: {server!r}"
    )
