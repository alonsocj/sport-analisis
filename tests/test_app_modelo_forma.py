"""Tests del panel 'Forma reciente vs v1' en la pestana Modelo (Feature 19, R1-R4).

Usa AppTest con artefacto JSON de fixture en tmp_path. 100% offline, sin red.
Mapeo: R1 -> test_carga_artefacto_ok, test_artefacto_ausente_no_rompe,
       test_json_malformado_no_rompe; R2 -> test_tabla_tiene_filas_y_delta_vs_v1,
       test_baseline_marcado_y_verdict_presente; R3 -> test_render_modelo_no_excepciona_con_panel,
       test_otras_secciones_y_tabs_intactas; R4 -> transversal (offline, sin red).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Artefacto sintetico (mismo schema que data/reports/forma_vs_v1.json real)
# ---------------------------------------------------------------------------

FORMA_ARTEFACTO_VALIDO: dict = {
    "titulo": "Forma reciente (F16) vs v1 — backtest medido",
    "from_date": "2026-06-14",
    "to_date": "2026-06-28",
    "n_eval": 191,
    "baseline": "dc-v1 (gamma=0)",
    "caveat": "Medido sobre continuacion de fase de grupos. Indicativo.",
    "rows": [
        {"gamma": 0.0, "log_loss": 0.8883, "brier": 0.5202, "accuracy": 0.5969, "is_baseline": True},
        {"gamma": 0.2, "log_loss": 0.8727, "brier": 0.5119, "accuracy": 0.5916, "is_baseline": False},
        {"gamma": 0.3, "log_loss": 0.8711, "brier": 0.5121, "accuracy": 0.5916, "is_baseline": False},
    ],
    "verdict": "La forma BATE a v1: log-loss 0.8883->0.8711 (g=0.3, -1.9%); Brier 0.5202->0.5119.",
    "fuente": "src.cli backtest --form-weight {0,0.2,0.3}",
}


# ---------------------------------------------------------------------------
# Helpers de insumos base (copiados de test_app_backtest_ui.py para independencia)
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
    "2026-06-11,Mexico,Argentina,NA,NA,FIFA World Cup,Mexico City,Mexico,FALSE",
)


def _make_params() -> dict:
    return {
        "as_of_date": AS_OF,
        "from_date": "2018-01-01",
        "xi": 0.35,
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
        "reg_lambda": 0.25,
        "low_data_teams": [],
        "convergencia": {
            "success": True, "n_iter": 57, "message": "ok", "neg_log_lik": 100.0
        },
    }


def _write_base_inputs(base: Path) -> dict[str, Path]:
    """Crea los insumos base de la app en base/ (gold + bronze).

    Args:
        base: Directorio raiz donde crear la estructura de datos sintetica.

    Returns:
        Dict con rutas a features, history, params y results.
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

    return {
        "features": features,
        "history": history,
        "params": params_path,
        "results": results,
    }


def _patch_app_defaults(monkeypatch, paths: dict[str, Path]) -> None:
    """Inyecta rutas sinteticas en src.app.data y src.app.main.

    Args:
        monkeypatch: Fixture de pytest.
        paths: Dict con rutas sinteticas (features, history, params, results).
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


def _run_app_forma(
    monkeypatch,
    paths: dict[str, Path],
    *,
    forma_path: Path | None,
) -> object:
    """Ejecuta AppTest con rutas inyectadas y artefacto forma controlado.

    Siempre apunta DEFAULT_BACKTEST_SUMMARY a una ruta inexistente para
    que la seccion Backtest degrade limpiamente (no es el foco de estos tests).

    Args:
        monkeypatch: Fixture de pytest.
        paths: Rutas base de la app (features, history, params, results).
        forma_path: Si no None, inyecta en DEFAULT_FORMA_VS_V1; si None,
                    apunta a una ruta inexistente (simula artefacto ausente).

    Returns:
        AppTest ejecutado.
    """
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod
    import src.app.tabs.modelo as modelo_mod

    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()

    _patch_app_defaults(monkeypatch, paths)

    # Siempre desviar el backtest summary a una ruta inexistente (degradacion limpia)
    monkeypatch.setattr(
        modelo_mod,
        "DEFAULT_BACKTEST_SUMMARY",
        paths["features"].parent / "_NO_EXISTE_summary.json",
    )

    if forma_path is not None:
        monkeypatch.setattr(modelo_mod, "DEFAULT_FORMA_VS_V1", forma_path)
    else:
        monkeypatch.setattr(
            modelo_mod,
            "DEFAULT_FORMA_VS_V1",
            paths["features"].parent / "_NO_EXISTE_forma_vs_v1.json",
        )

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=15.0)
    at.run()
    return at


# ---------------------------------------------------------------------------
# R1 — Carga del artefacto de comparativa
# ---------------------------------------------------------------------------


def test_carga_artefacto_ok(tmp_path: Path, monkeypatch) -> None:
    """R1: artefacto valido -> verdict en st.success, sin st.info de error."""
    artefacto = tmp_path / "forma_vs_v1.json"
    artefacto.write_text(json.dumps(FORMA_ARTEFACTO_VALIDO), encoding="utf-8")

    paths = _write_base_inputs(tmp_path)
    at = _run_app_forma(monkeypatch, paths, forma_path=artefacto)

    assert not at.exception, f"AppTest exception inesperada: {at.exception}"

    # El verdict debe aparecer en st.success
    all_success = [str(s.value) for s in at.success]
    assert len(all_success) >= 1, (
        f"Se esperaba st.success con el verdict; success={all_success!r}"
    )
    combined_success = " ".join(all_success)
    assert "bate" in combined_success.lower() or "v1" in combined_success.lower(), (
        f"Verdict no encontrado en st.success: {all_success!r}"
    )


def test_artefacto_ausente_no_rompe(tmp_path: Path, monkeypatch) -> None:
    """R1: artefacto ausente -> st.info accionable, sin excepcion."""
    paths = _write_base_inputs(tmp_path)
    # forma_path=None -> apunta a ruta inexistente
    at = _run_app_forma(monkeypatch, paths, forma_path=None)

    assert not at.exception, f"AppTest exception inesperada: {at.exception}"

    all_infos = [str(i.value) for i in at.info]
    combined = " ".join(all_infos)
    assert "backtest" in combined.lower() or "forma" in combined.lower(), (
        f"st.info accionable no encontrado: infos={all_infos!r}"
    )


def test_json_malformado_no_rompe(tmp_path: Path, monkeypatch) -> None:
    """R1: JSON sintaticamente invalido -> st.info accionable, sin excepcion."""
    artefacto = tmp_path / "forma_vs_v1_bad.json"
    artefacto.write_text("{ INVALID JSON >>> malformado", encoding="utf-8")

    paths = _write_base_inputs(tmp_path)
    at = _run_app_forma(monkeypatch, paths, forma_path=artefacto)

    assert not at.exception, f"AppTest exception inesperada: {at.exception}"

    all_infos = [str(i.value) for i in at.info]
    assert len(all_infos) >= 1, (
        f"Se esperaba st.info cuando el JSON esta malformado; infos={all_infos!r}"
    )
    combined = " ".join(all_infos)
    assert "regenera" in combined.lower() or "backtest" in combined.lower(), (
        f"st.info no menciona como regenerar el archivo: {all_infos!r}"
    )


# ---------------------------------------------------------------------------
# R2 — Render de la comparativa con delta vs v1
# ---------------------------------------------------------------------------


def test_tabla_tiene_filas_y_delta_vs_v1(tmp_path: Path, monkeypatch) -> None:
    """R2: tabla renderizada con 3 filas (gamma 0/0.2/0.3) y columnas delta vs v1."""
    artefacto = tmp_path / "forma_vs_v1.json"
    artefacto.write_text(json.dumps(FORMA_ARTEFACTO_VALIDO), encoding="utf-8")

    paths = _write_base_inputs(tmp_path)
    at = _run_app_forma(monkeypatch, paths, forma_path=artefacto)

    assert not at.exception, f"AppTest exception inesperada: {at.exception}"

    # Debe haber al menos un st.dataframe con la tabla de gammas
    assert len(at.dataframe) >= 1, (
        "Se esperaba al menos un st.dataframe con la tabla de comparativa"
    )

    df = at.dataframe[0].value  # pandas DataFrame o similar
    assert len(df) == 3, (
        f"Se esperaban 3 filas (gamma 0, 0.2, 0.3); se encontraron {len(df)}"
    )

    # Las columnas delta deben estar presentes
    cols_str = " ".join(str(c) for c in df.columns)
    assert "Δ" in cols_str, (
        f"Columnas delta (Δ) no encontradas en la tabla: columnas={list(df.columns)}"
    )
    assert "log-loss" in cols_str.lower() or "log_loss" in cols_str.lower(), (
        f"Columna log-loss no encontrada: columnas={list(df.columns)}"
    )


def test_baseline_marcado_y_verdict_presente(tmp_path: Path, monkeypatch) -> None:
    """R2: fila baseline marcada con etiqueta 'v1'; verdict presente en st.success."""
    artefacto = tmp_path / "forma_vs_v1.json"
    artefacto.write_text(json.dumps(FORMA_ARTEFACTO_VALIDO), encoding="utf-8")

    paths = _write_base_inputs(tmp_path)
    at = _run_app_forma(monkeypatch, paths, forma_path=artefacto)

    assert not at.exception, f"AppTest exception inesperada: {at.exception}"

    # La fila baseline debe estar marcada con "(v1)" en la columna gamma
    assert len(at.dataframe) >= 1
    df = at.dataframe[0].value
    gamma_col = df.iloc[:, 0]  # primera columna = γ
    gamma_values = [str(v) for v in gamma_col]
    assert any("v1" in v.lower() for v in gamma_values), (
        f"La etiqueta 'v1' no aparece en la columna gamma: {gamma_values!r}"
    )

    # El verdict debe aparecer en st.success
    all_success = [str(s.value) for s in at.success]
    assert len(all_success) >= 1, (
        f"Se esperaba st.success con el verdict; success={all_success!r}"
    )


# ---------------------------------------------------------------------------
# R3 — Integracion sin regresion
# ---------------------------------------------------------------------------


def test_render_modelo_no_excepciona_con_panel(tmp_path: Path, monkeypatch) -> None:
    """R3: render_modelo con el panel forma no lanza excepcion; metricas previas intactas."""
    artefacto = tmp_path / "forma_vs_v1.json"
    artefacto.write_text(json.dumps(FORMA_ARTEFACTO_VALIDO), encoding="utf-8")

    paths = _write_base_inputs(tmp_path)
    at = _run_app_forma(monkeypatch, paths, forma_path=artefacto)

    assert not at.exception, f"AppTest exception inesperada: {at.exception}"

    # Metadatos del modelo (seccion preexistente) siguen presentes
    all_metrics = [str(m.label) for m in at.metric]
    assert any("as_of" in m.lower() or "xi" in m.lower() for m in all_metrics), (
        f"Metadatos del modelo no encontrados tras agregar el panel forma: {all_metrics!r}"
    )


def test_otras_secciones_y_tabs_intactas(tmp_path: Path, monkeypatch) -> None:
    """R3: las tres pestanas (Calendario/Selecciones/Modelo) siguen presentes con el panel."""
    from src.app.main import TAB_CALENDARIO, TAB_MODELO, TAB_SELECCIONES

    artefacto = tmp_path / "forma_vs_v1.json"
    artefacto.write_text(json.dumps(FORMA_ARTEFACTO_VALIDO), encoding="utf-8")

    paths = _write_base_inputs(tmp_path)
    at = _run_app_forma(monkeypatch, paths, forma_path=artefacto)

    assert not at.exception, f"AppTest exception inesperada: {at.exception}"

    tab_labels = [t.label for t in at.tabs]
    assert TAB_CALENDARIO in tab_labels, (
        f"Falta pestana {TAB_CALENDARIO!r}; tabs={tab_labels!r}"
    )
    assert TAB_SELECCIONES in tab_labels, (
        f"Falta pestana {TAB_SELECCIONES!r}; tabs={tab_labels!r}"
    )
    assert TAB_MODELO in tab_labels, (
        f"Falta pestana {TAB_MODELO!r}; tabs={tab_labels!r}"
    )
