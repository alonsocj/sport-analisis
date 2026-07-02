"""Tests de la pestana Knockouts (Feature 17: R1–R5).

Cubre exactamente la tabla de trazabilidad de specs/knockouts_app/tasks.md.
100 % offline, cero red, as_of inyectado, form_builder inyectado.
No toca bronze, CLI, simulate ni datos reales del disco.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers de datos sinteticos (R5: offline)
# ---------------------------------------------------------------------------

AS_OF = "2026-06-01"

# Params minimos con ARG y BRA para tests de prediccion
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

# CSV de llaves minimo: 3 filas en orden de fecha no cronologico para probar el sort
_KO_CSV_CONTENT = """\
draw_order,date,stage,home_code,away_code,source
2,2026-07-01,R32,FRA,MEX,test
1,2026-06-29,R32,ARG,BRA,test
3,2026-07-01,R32,USA,CAN,test
"""

# CSV de features y elo_history minimos para AppTest
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
_HISTORY_ROW = "2025-10-01,ARG,BRA,2080.0,2090.0,35.0,1.0,0.55,1.0"


def _make_gold(tmp_path: Path) -> dict[str, Path]:
    """Crea insumos gold sinteticos en tmp_path y devuelve dict de rutas."""
    gold = tmp_path / "data" / "gold"
    gold.mkdir(parents=True, exist_ok=True)

    features = gold / "team_features.csv"
    features.write_text(
        "\n".join([_FEATURES_HEADER, *_FEATURES_ROWS]) + "\n", encoding="utf-8"
    )

    history = gold / "elo_history.csv"
    history.write_text(
        "\n".join([_HISTORY_HEADER, _HISTORY_ROW]) + "\n", encoding="utf-8"
    )

    params_path = gold / "dixon_coles_params.json"
    params_path.write_text(json.dumps(_PARAMS_DICT), encoding="utf-8")

    return {"features": features, "history": history, "params": params_path}


def _make_ko_csv(tmp_path: Path, content: str = _KO_CSV_CONTENT) -> Path:
    """Crea un CSV de llaves sintetico en tmp_path."""
    ko_dir = tmp_path / "data" / "knockouts"
    ko_dir.mkdir(parents=True, exist_ok=True)
    ko_csv = ko_dir / "r32_fixtures.csv"
    ko_csv.write_text(content, encoding="utf-8")
    return ko_csv


def _load_real_params():
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


# ---------------------------------------------------------------------------
# R1 — Carga de fixtures desde CSV
# ---------------------------------------------------------------------------


def test_carga_fixtures_csv_ordenado(tmp_path: Path) -> None:
    """R1: load_knockout_fixtures ordena por (date, draw_order)."""
    from src.app.tabs.knockouts import load_knockout_fixtures

    ko_csv = _make_ko_csv(tmp_path)
    fixtures = load_knockout_fixtures(ko_csv)

    assert len(fixtures) == 3

    # Orden esperado: (2026-06-29, draw_order=1), (2026-07-01, draw_order=2),
    # (2026-07-01, draw_order=3)
    assert fixtures[0].date == "2026-06-29"
    assert fixtures[0].draw_order == 1
    assert fixtures[0].home_code == "ARG"
    assert fixtures[0].away_code == "BRA"

    assert fixtures[1].date == "2026-07-01"
    assert fixtures[1].draw_order == 2

    assert fixtures[2].date == "2026-07-01"
    assert fixtures[2].draw_order == 3


def test_csv_ausente_no_rompe(tmp_path: Path) -> None:
    """R1: archivo ausente devuelve [] sin excepcion (degradacion elegante)."""
    from src.app.tabs.knockouts import load_knockout_fixtures

    resultado = load_knockout_fixtures(tmp_path / "no_existe.csv")
    assert resultado == []


def test_csv_vacio_no_rompe(tmp_path: Path) -> None:
    """R1: CSV con solo cabecera (sin filas de datos) devuelve []."""
    from src.app.tabs.knockouts import load_knockout_fixtures

    csv_solo_header = tmp_path / "empty.csv"
    csv_solo_header.write_text(
        "draw_order,date,stage,home_code,away_code,source\n", encoding="utf-8"
    )
    resultado = load_knockout_fixtures(csv_solo_header)
    assert resultado == []


# ---------------------------------------------------------------------------
# R2 — gamma=0 equivale a v1
# ---------------------------------------------------------------------------


def test_gamma0_equivale_v1() -> None:
    """R2: neutral_prediction con form_factor=None produce prediccion v1 exacta.

    Verifica que pasar form_factor=None (camino de gamma=0) da resultado
    identico a pasar un callable identidad (mult=1.0), con tolerancia 1e-9.
    """
    from src.app.tabs.knockouts import neutral_prediction

    params = _load_real_params()

    # Camino v1: form_factor=None
    result_none = neutral_prediction(params, "ARG", "BRA", form_factor=None)

    # Callable identidad: devuelve (1.0, 1.0) → lambda inalterada → mismo resultado
    def identity(home: str, away: str) -> tuple[float, float]:
        return 1.0, 1.0

    result_identity = neutral_prediction(params, "ARG", "BRA", form_factor=identity)

    assert abs(result_none["p_home"] - result_identity["p_home"]) < 1e-9
    assert abs(result_none["p_draw"] - result_identity["p_draw"]) < 1e-9
    assert abs(result_none["p_away"] - result_identity["p_away"]) < 1e-9
    assert abs(result_none["p_adv_home"] - result_identity["p_adv_home"]) < 1e-9


def test_gamma_positivo_aplica_forma() -> None:
    """R2: con form_factor != None la prediccion difiere de v1."""
    from src.app.tabs.knockouts import neutral_prediction

    params = _load_real_params()
    result_v1 = neutral_prediction(params, "ARG", "BRA", form_factor=None)

    # Factor que boosteea fuertemente a ARG y perjudica a BRA
    def boosted(home: str, away: str) -> tuple[float, float]:
        mults = {"ARG": 3.0, "BRA": 0.3}
        return mults.get(home, 1.0), mults.get(away, 1.0)

    result_forma = neutral_prediction(params, "ARG", "BRA", form_factor=boosted)

    # ARG boosted → p_home debe subir respecto a v1
    assert result_forma["p_home"] > result_v1["p_home"]
    assert result_forma["p_adv_home"] > result_v1["p_adv_home"]


# ---------------------------------------------------------------------------
# R3 — Prediccion neutral: formula de promedio de orientaciones
# ---------------------------------------------------------------------------


def test_neutral_promedia_orientaciones() -> None:
    """R3: neutral_prediction promedia (pred_AB, pred_BA) y renormaliza."""
    from src.app.tabs.knockouts import neutral_prediction
    from src.models.dixon_coles import predict_match

    params = _load_real_params()

    pred_ab = predict_match(params, "ARG", "BRA", form_factor=None)
    pred_ba = predict_match(params, "BRA", "ARG", form_factor=None)

    # Formula esperada (antes de renorm)
    ph_raw = (pred_ab.prob_home + pred_ba.prob_away) / 2.0
    pd_raw = (pred_ab.prob_draw + pred_ba.prob_draw) / 2.0
    pa_raw = (pred_ab.prob_away + pred_ba.prob_home) / 2.0
    total = ph_raw + pd_raw + pa_raw

    result = neutral_prediction(params, "ARG", "BRA", form_factor=None)

    assert abs(result["p_home"] - ph_raw / total) < 1e-9
    assert abs(result["p_draw"] - pd_raw / total) < 1e-9
    assert abs(result["p_away"] - pa_raw / total) < 1e-9


def test_p_avanza_formula() -> None:
    """R3: p_adv_home = p_home + 0.5 * p_draw; las tres probs suman 1."""
    from src.app.tabs.knockouts import neutral_prediction

    params = _load_real_params()
    result = neutral_prediction(params, "ARG", "BRA", form_factor=None)

    expected_adv = result["p_home"] + 0.5 * result["p_draw"]
    assert abs(result["p_adv_home"] - expected_adv) < 1e-9

    # Sanidad: las tres probabilidades suman 1.0
    total = result["p_home"] + result["p_draw"] + result["p_away"]
    assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# R4 — Render no excepciona; pestanas existentes intactas
# ---------------------------------------------------------------------------


def _write_apptest_inputs(tmp_path: Path, ko_csv: Path) -> dict[str, Path]:
    """Crea todos los insumos necesarios para AppTest con pestaña Knockouts."""
    paths = _make_gold(tmp_path)

    # Bronze opcional (para Calendario; puede estar ausente)
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
    """Inyecta rutas sinteticas en src.app.data, src.app.main y src.app.tabs.knockouts."""
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

    # Ruta al CSV de llaves sintetico (R1)
    monkeypatch.setattr(ko_mod, "DEFAULT_KO_CSV", paths["ko_csv"])


def _get_app(monkeypatch, paths: dict[str, Path], *, timeout: float = 15.0):
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


def test_render_no_excepciona(tmp_path: Path, monkeypatch) -> None:
    """R4: la app con pestaña Knockouts no lanza excepcion con CSV valido."""
    ko_csv = _make_ko_csv(tmp_path)
    paths = _write_apptest_inputs(tmp_path, ko_csv)

    at = _get_app(monkeypatch, paths)
    assert not at.exception, f"AppTest lanzo excepcion: {at.exception}"


def test_tabs_existentes_intactas(tmp_path: Path, monkeypatch) -> None:
    """R4: las cuatro pestanas (Calendario, Selecciones, Modelo, Knockouts) estan presentes.

    Verifica que añadir Knockouts no altera las tres pestanas originales.
    """
    from src.app.main import TAB_CALENDARIO, TAB_MODELO, TAB_SELECCIONES, TAB_KNOCKOUTS

    ko_csv = _make_ko_csv(tmp_path)
    paths = _write_apptest_inputs(tmp_path, ko_csv)

    at = _get_app(monkeypatch, paths)
    assert not at.exception, f"AppTest lanzo excepcion: {at.exception}"

    tab_labels = [t.label for t in at.tabs]
    assert TAB_CALENDARIO in tab_labels, f"Falta {TAB_CALENDARIO!r} en {tab_labels}"
    assert TAB_SELECCIONES in tab_labels, f"Falta {TAB_SELECCIONES!r} en {tab_labels}"
    assert TAB_MODELO in tab_labels, f"Falta {TAB_MODELO!r} en {tab_labels}"
    assert TAB_KNOCKOUTS in tab_labels, f"Falta {TAB_KNOCKOUTS!r} en {tab_labels}"


# ---------------------------------------------------------------------------
# R5 — form_builder se llama 1 vez por render (gate 6)
# ---------------------------------------------------------------------------


def test_form_builder_llamado_una_vez_por_render(tmp_path: Path, monkeypatch) -> None:
    """R5/Gate6: render_knockouts llama a form_builder exactamente 1 vez con gamma>0.

    Verifica que la construccion del factor de forma es O(1) en numero de llaves,
    no O(n_llaves). Prueba las funciones puras directamente sin servidor Streamlit.
    """
    import unittest.mock as mock
    import streamlit as st

    params = _load_real_params()
    ko_csv = _make_ko_csv(tmp_path)

    # form_builder contador: devuelve identity y cuenta llamadas
    call_count = {"n": 0}

    def counting_builder(matches, as_of, elo, gamma, teams, use_xg=False):
        call_count["n"] += 1
        # Devuelve un callable identity para no necesitar datos reales
        def identity(home: str, away: str) -> tuple[float, float]:
            return 1.0, 1.0
        return identity

    # Mockeamos streamlit para evitar error "no active script run context"
    with mock.patch("streamlit.slider", return_value=0.5), \
         mock.patch("streamlit.warning"), \
         mock.patch("streamlit.info"), \
         mock.patch("streamlit.subheader"), \
         mock.patch("streamlit.container") as mock_container, \
         mock.patch("streamlit.columns", return_value=[mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]), \
         mock.patch("streamlit.markdown"), \
         mock.patch("streamlit.caption"), \
         mock.patch("pandas.read_csv", return_value=__import__("pandas").DataFrame(
             {"date": ["2026-01-01"], "home_code": ["ARG"], "away_code": ["BRA"],
              "neutral": [1], "home_goals": [1], "away_goals": [0],
              "tournament": ["friendly"], "match_id": [1]}
         )):

        # mock_container como context manager
        mock_container.return_value.__enter__ = mock.MagicMock(return_value=mock.MagicMock())
        mock_container.return_value.__exit__ = mock.MagicMock(return_value=False)

        from src.app.tabs.knockouts import render_knockouts
        from src.app.data import AppData, load_params

        # Construir AppData minimo
        gold = _make_gold(tmp_path)
        from src.app.data import load_app_data
        app_data = load_app_data(
            features_csv=str(gold["features"]),
            elo_history_csv=str(gold["history"]),
            params_path=str(gold["params"]),
        )

        render_knockouts(app_data, fixtures_csv=ko_csv, form_builder=counting_builder)

    # Con 3 llaves en el CSV, form_builder se llama exactamente 1 vez (no 3)
    assert call_count["n"] == 1, (
        f"form_builder se llamo {call_count['n']} vez/veces; se esperaba exactamente 1"
    )


def test_gamma0_no_llama_form_builder(tmp_path: Path) -> None:
    """R2/Gate1: con gamma=0, form_builder NO se llama (form_factor=None exacto)."""
    import unittest.mock as mock

    params = _load_real_params()
    ko_csv = _make_ko_csv(tmp_path)

    call_count = {"n": 0}

    def counting_builder(matches, as_of, elo, gamma, teams, use_xg=False):
        call_count["n"] += 1
        return lambda h, a: (1.0, 1.0)

    with mock.patch("streamlit.slider", return_value=0.0), \
         mock.patch("streamlit.warning"), \
         mock.patch("streamlit.info"), \
         mock.patch("streamlit.subheader"), \
         mock.patch("streamlit.container") as mock_container, \
         mock.patch("streamlit.columns", return_value=[mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]), \
         mock.patch("streamlit.markdown"), \
         mock.patch("streamlit.caption"):

        mock_container.return_value.__enter__ = mock.MagicMock(return_value=mock.MagicMock())
        mock_container.return_value.__exit__ = mock.MagicMock(return_value=False)

        from src.app.tabs.knockouts import render_knockouts
        from src.app.data import load_app_data

        gold = _make_gold(tmp_path)
        app_data = load_app_data(
            features_csv=str(gold["features"]),
            elo_history_csv=str(gold["history"]),
            params_path=str(gold["params"]),
        )

        render_knockouts(app_data, fixtures_csv=ko_csv, form_builder=counting_builder)

    # Con gamma=0, form_builder NO debe llamarse → form_factor=None exacto (no-regresion)
    assert call_count["n"] == 0, (
        f"form_builder se llamo {call_count['n']} vez/veces con gamma=0; se esperaba 0"
    )
