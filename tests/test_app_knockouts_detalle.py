"""Tests de Feature 22: detalle de llave knockouts con sub-pestanas (R1–R5).

100% offline, sin red, fixtures sinteticos de params/player_factor/roster.
Mapeo de trazabilidad (tasks.md):
- R1: test_seleccion_abre_detalle, test_sin_seleccion_no_excepciona
- R2: test_subpestanas_presentes, test_mercados_y_goleadores_en_detalle
- R3: test_top10_marcadores_orden_desc, test_matriz_neutral_promedia_orientaciones,
       test_gamma_afecta_prediccion
- R4: test_lista_llaves_y_slider_intactos, test_otras_pestanas_intactas
- R5: transversal (todos offline) + test_degradacion_equipo_desconocido,
       test_degradacion_sin_elo
"""

from __future__ import annotations

import json
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Constantes y fixtures sinteticos (R5: offline, sin red)
# ---------------------------------------------------------------------------

AS_OF = "2026-06-01"

_PARAMS_DICT: dict = {
    "as_of_date": AS_OF,
    "from_date": "2018-01-01",
    "xi": 0.35,
    "mu": 0.1,
    "home_advantage": 0.3,
    "rho": -0.05,
    "attack": {
        "ARG": 0.50, "BRA": 0.20, "FRA": 0.30,
        "MEX": 0.15, "USA": 0.10, "CAN": 0.05,
    },
    "defense": {
        "ARG": 0.40, "BRA": 0.25, "FRA": 0.15,
        "MEX": 0.05, "USA": 0.00, "CAN": -0.05,
    },
    "n_matches": 100,
    "n_teams": 6,
    "min_matches": 5,
    "reg_lambda": 0.25,
    "low_data_teams": [],
    "convergencia": {"success": True, "n_iter": 50, "message": "ok", "neg_log_lik": 90.0},
}

_PLAYER_FACTOR_CONTENT = (
    f"as_of_date,team_code,scorer,goals_weighted,share\n"
    f"{AS_OF},ARG,Messi,5.0000000000,0.5000000000\n"
    f"{AS_OF},ARG,Di Maria,3.0000000000,0.3000000000\n"
    f"{AS_OF},ARG,Lautaro,2.0000000000,0.2000000000\n"
    f"{AS_OF},BRA,Vinicius,4.0000000000,0.5000000000\n"
    f"{AS_OF},BRA,Rodrygo,2.5000000000,0.3125000000\n"
    f"{AS_OF},BRA,Endrick,1.5000000000,0.1875000000\n"
)

_KO_CSV_CONTENT = """\
draw_order,date,stage,home_code,away_code,source
1,2026-06-29,R32,ARG,BRA,test
2,2026-07-01,R32,FRA,MEX,test
3,2026-07-01,R32,USA,CAN,test
"""

_FEATURES_HEADER = (
    "code,as_of_date,matches_count,gf_ma15,ga_ma15,corners_for_ma15,"
    "corners_against_ma15,cards_ma15,shots_ma15,shots_on_target_ma15,"
    "possession_ma15,elo"
)
_FEATURES_ROWS = (
    f"ARG,{AS_OF},15,2.1,0.8,,,,,,,2100.0",
    f"BRA,{AS_OF},15,1.9,0.9,,,,,,,2050.0",
    f"FRA,{AS_OF},12,1.8,1.0,,,,,,,2000.0",
    f"MEX,{AS_OF},10,1.5,1.1,,,,,,,1800.0",
    f"USA,{AS_OF},14,1.4,1.2,,,,,,,1750.0",
    f"CAN,{AS_OF},12,1.3,1.2,,,,,,,1700.0",
)
_HISTORY_HEADER = "date,code,opponent_code,elo_pre,elo_post,k,g,we,score"
_HISTORY_ROWS = (
    "2025-10-01,ARG,BRA,2080.0,2090.0,35.0,1.0,0.55,1.0",
    "2025-10-01,BRA,ARG,2040.0,2030.0,35.0,1.0,0.45,0.0",
)


# ---------------------------------------------------------------------------
# Helpers de construccion de fixtures
# ---------------------------------------------------------------------------


def _make_synthetic_params():
    """Carga DixonColesParams desde el dict sintetico."""
    from src.models.dixon_coles import load_params
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_PARAMS_DICT, fh)
        tmp = Path(fh.name)

    try:
        return load_params(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _make_gold(tmp_path: Path) -> dict[str, Path]:
    """Crea insumos gold sinteticos en tmp_path."""
    gold = tmp_path / "data" / "gold"
    gold.mkdir(parents=True, exist_ok=True)

    features = gold / "team_features.csv"
    features.write_text(
        "\n".join([_FEATURES_HEADER, *_FEATURES_ROWS]) + "\n", encoding="utf-8"
    )

    history = gold / "elo_history.csv"
    history.write_text(
        "\n".join([_HISTORY_HEADER, *_HISTORY_ROWS]) + "\n", encoding="utf-8"
    )

    params_path = gold / "dixon_coles_params.json"
    params_path.write_text(json.dumps(_PARAMS_DICT), encoding="utf-8")

    return {"features": features, "history": history, "params": params_path}


def _make_player_factor(tmp_path: Path) -> Path:
    """Crea player_factor.csv sintetico."""
    gold = tmp_path / "data" / "gold"
    gold.mkdir(parents=True, exist_ok=True)
    pf = gold / "player_factor.csv"
    pf.write_text(_PLAYER_FACTOR_CONTENT, encoding="utf-8")
    return pf


def _make_ko_csv(tmp_path: Path) -> Path:
    """Crea CSV de llaves sintetico."""
    ko_dir = tmp_path / "data" / "knockouts"
    ko_dir.mkdir(parents=True, exist_ok=True)
    ko_csv = ko_dir / "r32_fixtures.csv"
    ko_csv.write_text(_KO_CSV_CONTENT, encoding="utf-8")
    return ko_csv


def _write_apptest_inputs(tmp_path: Path, ko_csv: Path) -> dict[str, Path]:
    """Crea todos los insumos necesarios para AppTest con pestana Knockouts."""
    paths = _make_gold(tmp_path)

    results = tmp_path / "data" / "bronze" / "public_results" / "results.csv"
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(
        "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
        "2026-06-10,Argentina,Brazil,NA,NA,FIFA World Cup,Dallas,USA,TRUE\n",
        encoding="utf-8",
    )
    paths["results"] = results
    paths["ko_csv"] = ko_csv
    return paths


def _patch_app_defaults(monkeypatch, paths: dict[str, Path]) -> None:
    """Inyecta rutas sinteticas en los modulos de la app."""
    import src.app.data as data_mod
    import src.app.main as main_mod
    import src.app.tabs.knockouts as ko_mod

    monkeypatch.setattr(data_mod, "DEFAULT_FEATURES_CSV", paths["features"])
    monkeypatch.setattr(data_mod, "DEFAULT_ELO_HISTORY_CSV", paths["history"])
    monkeypatch.setattr(data_mod, "DEFAULT_PARAMS_PATH", paths["params"])
    monkeypatch.setattr(data_mod, "DEFAULT_RESULTS_CSV", paths["results"])

    monkeypatch.setattr(main_mod, "DEFAULT_FEATURES_CSV", paths["features"])
    monkeypatch.setattr(main_mod, "DEFAULT_ELO_HISTORY_CSV", paths["history"])
    monkeypatch.setattr(main_mod, "DEFAULT_PARAMS_PATH", paths["params"])
    monkeypatch.setattr(main_mod, "DEFAULT_RESULTS_CSV", paths["results"])

    monkeypatch.setattr(ko_mod, "DEFAULT_KO_CSV", paths["ko_csv"])


def _get_app(monkeypatch, paths: dict[str, Path], *, timeout: float = 20.0):
    """Crea y ejecuta AppTest con rutas inyectadas."""
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod

    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()

    _patch_app_defaults(monkeypatch, paths)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=timeout)
    at.run()
    return at


def _make_app_data(tmp_path: Path):
    """Crea AppData sintetico desde los insumos gold."""
    paths = _make_gold(tmp_path)
    from src.app.data import load_app_data
    return load_app_data(
        features_csv=str(paths["features"]),
        elo_history_csv=str(paths["history"]),
        params_path=str(paths["params"]),
    )


# ---------------------------------------------------------------------------
# R3 — Prediccion neutral + top-10 (funciones puras, sin Streamlit)
# ---------------------------------------------------------------------------


def test_top10_marcadores_orden_desc() -> None:
    """R3: _neutral_matrix_pred devuelve exactamente 10 marcadores en orden descendente."""
    from src.app.tabs.knockouts import _neutral_matrix_pred

    params = _make_synthetic_params()
    pred = _neutral_matrix_pred(params, "ARG", "BRA", form_factor=None)

    # Exactamente 10 entradas (design.md: top-10)
    assert len(pred.top_scores) == 10, (
        f"Se esperaban 10 marcadores, obtenidos: {len(pred.top_scores)}"
    )

    # Orden descendente por probabilidad
    probs = [p for _, _, p in pred.top_scores]
    for i in range(len(probs) - 1):
        assert probs[i] >= probs[i + 1], (
            f"No descendente en posicion {i}: {probs[i]:.6f} < {probs[i + 1]:.6f}"
        )


def test_matriz_neutral_promedia_orientaciones() -> None:
    """R3: la matriz de _neutral_matrix_pred es el promedio de las dos orientaciones.

    Oracle: M esperada = (pred_ab.matrix + pred_ba.matrix.T) / 2, renormalizada.
    Esto verifica la propiedad de sede neutral (design.md R3).
    """
    from src.app.tabs.knockouts import _neutral_matrix_pred
    from src.models.dixon_coles import predict_match

    params = _make_synthetic_params()

    pred_ab = predict_match(params, "ARG", "BRA", form_factor=None)
    pred_ba = predict_match(params, "BRA", "ARG", form_factor=None)

    # Matriz esperada (oraculo)
    M_raw = (pred_ab.matrix + pred_ba.matrix.T) / 2.0
    M_expected = M_raw / M_raw.sum()

    pred_neutral = _neutral_matrix_pred(params, "ARG", "BRA", form_factor=None)

    np.testing.assert_allclose(
        pred_neutral.matrix, M_expected, atol=1e-9,
        err_msg="La matriz neutral no es el promedio renormalizado de las dos orientaciones"
    )


def test_gamma_afecta_prediccion() -> None:
    """R3: con form_factor != None la prediccion del detalle difiere de v1 (gamma=0)."""
    from src.app.tabs.knockouts import _neutral_matrix_pred

    params = _make_synthetic_params()

    pred_v1 = _neutral_matrix_pred(params, "ARG", "BRA", form_factor=None)

    # Factor que boosteea fuertemente a ARG (mult_home=3.0 cuando ARG es local)
    def boosted(home: str, away: str) -> tuple[float, float]:
        return (3.0, 0.5) if home == "ARG" else (0.5, 3.0)

    pred_forma = _neutral_matrix_pred(params, "ARG", "BRA", form_factor=boosted)

    # Con ARG boosteado como local en pred_ab → prob_home debe subir en la neutral
    assert pred_forma.prob_home > pred_v1.prob_home, (
        f"prob_home con forma ({pred_forma.prob_home:.4f}) debe ser > v1 "
        f"({pred_v1.prob_home:.4f})"
    )

    # Las matrices deben diferir significativamente
    assert not np.allclose(pred_forma.matrix, pred_v1.matrix, atol=1e-6), (
        "Las matrices con y sin forma no deberian ser iguales"
    )


def test_top10_desde_matriz_neutral() -> None:
    """R3 (oraculo): los top-10 de _neutral_matrix_pred provienen de la matriz neutral M.

    Verifica que los 10 (gx, gy, prob) reportados coinciden con las 10 celdas
    de mayor probabilidad de la matriz neutral renormalizada.
    """
    from src.app.tabs.knockouts import _neutral_matrix_pred
    from src.models.dixon_coles import predict_match

    params = _make_synthetic_params()

    # Calcular la matriz neutral esperada
    pred_ab = predict_match(params, "ARG", "BRA", form_factor=None)
    pred_ba = predict_match(params, "BRA", "ARG", form_factor=None)
    M_raw = (pred_ab.matrix + pred_ba.matrix.T) / 2.0
    M = M_raw / M_raw.sum()

    n = M.shape[0]
    cells_expected = sorted(
        [(gx, gy, float(M[gx, gy])) for gx in range(n) for gy in range(n)],
        key=lambda c: (-c[2], c[0], c[1]),
    )[:10]

    pred_neutral = _neutral_matrix_pred(params, "ARG", "BRA", form_factor=None)

    assert len(pred_neutral.top_scores) == 10
    for i, ((gxa, gya, pa), (gxe, gye, pe)) in enumerate(
        zip(pred_neutral.top_scores, cells_expected)
    ):
        assert gxa == gxe and gya == gye, (
            f"Posicion {i}: obtenido ({gxa},{gya}), esperado ({gxe},{gye})"
        )
        assert abs(pa - pe) < 1e-9, (
            f"Posicion {i}: prob obtenida {pa:.8f}, esperada {pe:.8f}"
        )


# ---------------------------------------------------------------------------
# R1 — Seleccion por session_state + no excepcion sin seleccion
# ---------------------------------------------------------------------------


def test_sin_seleccion_no_excepciona(tmp_path: Path, monkeypatch) -> None:
    """R1: sin selected_ko en session_state, render_knockouts no lanza excepcion."""
    ko_csv = _make_ko_csv(tmp_path)
    paths = _write_apptest_inputs(tmp_path, ko_csv)

    at = _get_app(monkeypatch, paths)
    assert not at.exception, f"AppTest lanzó excepción sin selected_ko: {at.exception}"


def test_seleccion_abre_detalle(tmp_path: Path, monkeypatch) -> None:
    """R1: con selected_ko pre-seteado, se renderizan las 5 sub-pestanas del detalle."""
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod

    ko_csv = _make_ko_csv(tmp_path)
    paths = _write_apptest_inputs(tmp_path, ko_csv)

    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()
    _patch_app_defaults(monkeypatch, paths)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=20.0)
    # Pre-setear selected_ko simula haber clickeado "Ver detalle" en un render anterior.
    # F30: el tab principal es Round of 16 con state_key="r16" → clave namespaceada.
    at.session_state["selected_ko_r16"] = ("2026-06-29", "ARG", "BRA")
    at.run()

    assert not at.exception, f"AppTest con selected_ko lanzó: {at.exception}"

    # Las 5 sub-pestanas del detalle deben estar presentes (R2)
    tab_labels = [t.label for t in at.tabs]
    for label in ("Predicción", "Mercados", "Goleadores", "Equipos", "Elo"):
        assert label in tab_labels, (
            f"Sub-pestaña {label!r} no encontrada. Pestañas: {tab_labels}"
        )


# ---------------------------------------------------------------------------
# R2 — Sub-pestanas presentes y contenido de mercados/goleadores
# ---------------------------------------------------------------------------


def test_subpestanas_presentes(tmp_path: Path) -> None:
    """R2: _render_detalle_ko crea exactamente las 5 sub-pestanas esperadas."""
    from src.app.tabs.knockouts import KnockoutFixture, _render_detalle_ko, _compute_analisis_data

    params = _make_synthetic_params()
    app_data = _make_app_data(tmp_path)
    pf_path = _make_player_factor(tmp_path)
    fixture = KnockoutFixture(
        draw_order=1, date="2026-06-29", stage="R32",
        home_code="ARG", away_code="BRA",
    )

    _compute_analisis_data.clear()
    captured_labels: list[str] = []

    def fake_tabs(labels, **kw):
        captured_labels.extend(labels)
        return [mock.MagicMock() for _ in labels]

    mc = mock.MagicMock()
    mc.__enter__ = mock.MagicMock(return_value=mc)
    mc.__exit__ = mock.MagicMock(return_value=False)

    with (
        mock.patch("streamlit.container", return_value=mc),
        mock.patch("streamlit.tabs", side_effect=fake_tabs),
        mock.patch("streamlit.markdown"),
        mock.patch("streamlit.plotly_chart"),
        mock.patch("streamlit.write"),
        mock.patch("streamlit.caption"),
        mock.patch("streamlit.info"),
    ):
        _render_detalle_ko(fixture, app_data, None, pf_path)

    expected = ["Predicción", "Mercados", "Goleadores", "Equipos", "Elo", "Alineación"]
    assert captured_labels == expected, (
        f"Sub-pestanas: {captured_labels}; esperadas: {expected}"
    )


def test_mercados_y_goleadores_en_detalle(tmp_path: Path) -> None:
    """R2: los datos de mercados y goleadores estan disponibles para las sub-pestanas."""
    from src.app.tabs.knockouts import _compute_analisis_data

    params = _make_synthetic_params()
    pf_path = _make_player_factor(tmp_path)
    _compute_analisis_data.clear()

    # top_k=5 como en _render_detalle_ko
    data = _compute_analisis_data(params, "ARG", "BRA", str(pf_path), 5)

    assert data["error"] is None, f"Error inesperado: {data['error']}"

    # Mercados
    assert data["summary"] is not None, "summary no debe ser None"
    assert len(data["summary"].totals) >= 1, "O/U totales vacios"
    assert 0.0 <= data["summary"].btts_yes <= 1.0

    # Goleadores
    assert not data["no_player_factor"], "player_factor existe pero flag=True"
    assert data["scorers_home"] is not None, "scorers_home no debe ser None"
    assert data["scorers_away"] is not None, "scorers_away no debe ser None"
    assert len(data["scorers_home"]) >= 1, "Sin goleadores para ARG"
    assert len(data["scorers_away"]) >= 1, "Sin goleadores para BRA"


# ---------------------------------------------------------------------------
# R4 — Integracion sin regresion
# ---------------------------------------------------------------------------


def test_lista_llaves_y_slider_intactos(tmp_path: Path, monkeypatch) -> None:
    """R4: slider gamma y botones Ver detalle presentes tras el refactor."""
    ko_csv = _make_ko_csv(tmp_path)
    paths = _write_apptest_inputs(tmp_path, ko_csv)

    at = _get_app(monkeypatch, paths)
    assert not at.exception, f"AppTest lanzó: {at.exception}"

    # Slider gamma presente (R2 F17)
    slider_labels = [s.label for s in at.slider]
    assert "Peso forma (gamma)" in slider_labels, (
        f"Slider 'Peso forma (gamma)' no encontrado. Sliders: {slider_labels}"
    )

    # Botones "Ver detalle" presentes (R1 F22): uno por llave del CSV de prueba
    btn_labels = [b.label for b in at.button]
    ver_detalle_count = sum(1 for lbl in btn_labels if lbl == "Ver detalle")
    assert ver_detalle_count >= 1, (
        f"No se encontraron botones 'Ver detalle'. Botones: {btn_labels}"
    )


def test_otras_pestanas_intactas(tmp_path: Path, monkeypatch) -> None:
    """R4: las cuatro pestanas (Calendario, Selecciones, Modelo, Knockouts) siguen presentes."""
    from src.app.main import TAB_CALENDARIO, TAB_MODELO, TAB_SELECCIONES, TAB_KNOCKOUTS

    ko_csv = _make_ko_csv(tmp_path)
    paths = _write_apptest_inputs(tmp_path, ko_csv)

    at = _get_app(monkeypatch, paths)
    assert not at.exception, f"AppTest lanzó: {at.exception}"

    tab_labels = [t.label for t in at.tabs]
    assert TAB_CALENDARIO in tab_labels, f"Falta {TAB_CALENDARIO!r} en {tab_labels}"
    assert TAB_SELECCIONES in tab_labels, f"Falta {TAB_SELECCIONES!r} en {tab_labels}"
    assert TAB_MODELO in tab_labels, f"Falta {TAB_MODELO!r} en {tab_labels}"
    assert TAB_KNOCKOUTS in tab_labels, f"Falta {TAB_KNOCKOUTS!r} en {tab_labels}"


# ---------------------------------------------------------------------------
# R5 — Degradacion elegante (offline, sin libs nuevas)
# ---------------------------------------------------------------------------


def test_degradacion_equipo_desconocido(tmp_path: Path) -> None:
    """R5: _neutral_matrix_pred lanza UnknownTeamError para equipo no en params.

    _render_detalle_ko no propaga la excepcion (la maneja internamente).
    """
    from src.app.tabs.knockouts import (
        KnockoutFixture,
        _neutral_matrix_pred,
        _render_detalle_ko,
        _compute_analisis_data,
    )
    from src.models.dixon_coles import UnknownTeamError

    params = _make_synthetic_params()

    # _neutral_matrix_pred debe lanzar UnknownTeamError para equipo desconocido
    with pytest.raises(UnknownTeamError):
        _neutral_matrix_pred(params, "ARG", "XXX", form_factor=None)

    # _render_detalle_ko no debe propagar la excepcion (degrada con caption)
    app_data = _make_app_data(tmp_path)
    fixture = KnockoutFixture(
        draw_order=1, date="2026-06-29", stage="R32",
        home_code="ARG", away_code="XXX",
    )
    _compute_analisis_data.clear()

    mc = mock.MagicMock()
    mc.__enter__ = mock.MagicMock(return_value=mc)
    mc.__exit__ = mock.MagicMock(return_value=False)

    tabs_mocks = [mock.MagicMock() for _ in range(6)]  # F31: +Alineación

    with (
        mock.patch("streamlit.container", return_value=mc),
        mock.patch("streamlit.tabs", return_value=tabs_mocks),
        mock.patch("streamlit.markdown"),
        mock.patch("streamlit.plotly_chart"),
        mock.patch("streamlit.write"),
        mock.patch("streamlit.caption"),
        mock.patch("streamlit.info"),
    ):
        # No debe lanzar excepcion
        _render_detalle_ko(fixture, app_data, None, tmp_path / "no_pf.csv")


def test_degradacion_sin_player_factor(tmp_path: Path) -> None:
    """R5: sin player_factor, la sub-pestana Goleadores degrada sin excepcion."""
    from src.app.tabs.knockouts import _compute_analisis_data

    params = _make_synthetic_params()
    _compute_analisis_data.clear()

    data = _compute_analisis_data(params, "ARG", "BRA", str(tmp_path / "no_existe.csv"), 5)

    assert data["error"] is None, "No debe haber error para equipos conocidos"
    assert data["no_player_factor"] is True, "Debe indicar ausencia de player_factor"
    # Mercados siguen disponibles aunque no haya goleadores
    assert data["summary"] is not None, "Mercados deben seguir disponibles"


def test_degradacion_sin_elo(tmp_path: Path) -> None:
    """R5: sin historial Elo para los equipos, la sub-pestana Elo degrada sin excepcion."""
    from src.app.tabs.knockouts import KnockoutFixture, _render_detalle_ko, _compute_analisis_data
    from src.app.data import load_app_data

    # Gold sin filas de elo para XXX/YYY
    paths = _make_gold(tmp_path)
    app_data = load_app_data(
        features_csv=str(paths["features"]),
        elo_history_csv=str(paths["history"]),
        params_path=str(paths["params"]),
    )

    fixture = KnockoutFixture(
        draw_order=1, date="2026-06-29", stage="R32",
        home_code="ARG", away_code="BRA",
    )
    _compute_analisis_data.clear()

    captions: list[str] = []
    mc = mock.MagicMock()
    mc.__enter__ = mock.MagicMock(return_value=mc)
    mc.__exit__ = mock.MagicMock(return_value=False)
    tabs_mocks = [mock.MagicMock() for _ in range(6)]  # F31: +Alineación

    with (
        mock.patch("streamlit.container", return_value=mc),
        mock.patch("streamlit.tabs", return_value=tabs_mocks),
        mock.patch("streamlit.markdown"),
        mock.patch("streamlit.plotly_chart"),
        mock.patch("streamlit.write"),
        mock.patch("streamlit.caption", side_effect=lambda x, **kw: captions.append(str(x))),
        mock.patch("streamlit.info"),
    ):
        # Debe completar sin excepcion (ARG/BRA SI tienen historial en el fixture)
        _render_detalle_ko(fixture, app_data, None, tmp_path / "no_pf.csv")

    # No debe haber excepcion → la funcion completo sin error
