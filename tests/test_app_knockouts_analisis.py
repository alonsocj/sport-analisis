"""Tests de Feature 20: panel de mercados y goleadores por llave (R1–R5).

100% offline, sin red, fixtures sinteticos de params y player_factor.
Monkeypatch de paths donde aplica. No toca core/cli/otras pestanas.
Mapeo: R1→test_mercados_*, R2→test_goleadores_*, test_sin_player_factor_*,
       R3→test_etiqueta_*, test_cache_*, R4→test_render_*, test_otras_*,
       R5→transversal (todos los tests son offline y sin libs nuevas).
"""

from __future__ import annotations

import json
from pathlib import Path

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

# Contenido sintetico de player_factor.csv (gold)
_PLAYER_FACTOR_CONTENT = (
    f"as_of_date,team_code,scorer,goals_weighted,share\n"
    f"{AS_OF},ARG,Messi,5.0000000000,0.5000000000\n"
    f"{AS_OF},ARG,Di Maria,3.0000000000,0.3000000000\n"
    f"{AS_OF},ARG,Lautaro,2.0000000000,0.2000000000\n"
    f"{AS_OF},BRA,Vinicius,4.0000000000,0.5000000000\n"
    f"{AS_OF},BRA,Rodrygo,2.5000000000,0.3125000000\n"
    f"{AS_OF},BRA,Endrick,1.5000000000,0.1875000000\n"
    f"{AS_OF},FRA,Mbappe,5.0000000000,0.6250000000\n"
    f"{AS_OF},FRA,Dembele,2.0000000000,0.2500000000\n"
    f"{AS_OF},FRA,Thuram,1.0000000000,0.1250000000\n"
)

_KO_CSV_CONTENT = """\
draw_order,date,stage,home_code,away_code,source
1,2026-06-29,R32,ARG,BRA,test
2,2026-07-01,R32,FRA,MEX,test
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


# ---------------------------------------------------------------------------
# Helpers de construction de fixtures
# ---------------------------------------------------------------------------


def _make_synthetic_params():
    """Carga DixonColesParams desde el dict sintetico (sin disco permanente)."""
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


def _make_player_factor(tmp_path: Path) -> Path:
    """Crea player_factor.csv sintetico en tmp_path/data/gold."""
    gold = tmp_path / "data" / "gold"
    gold.mkdir(parents=True, exist_ok=True)
    pf = gold / "player_factor.csv"
    pf.write_text(_PLAYER_FACTOR_CONTENT, encoding="utf-8")
    return pf


def _make_gold(tmp_path: Path) -> dict[str, Path]:
    """Crea insumos gold sinteticos completos para AppTest."""
    gold = tmp_path / "data" / "gold"
    gold.mkdir(parents=True, exist_ok=True)

    features = gold / "team_features.csv"
    features.write_text(
        "\n".join([_FEATURES_HEADER, *_FEATURES_ROWS]) + "\n", encoding="utf-8"
    )

    history = gold / "elo_history.csv"
    history.write_text(
        "date,code,opponent_code,elo_pre,elo_post,k,g,we,score\n"
        "2025-10-01,ARG,BRA,2080.0,2090.0,35.0,1.0,0.55,1.0\n",
        encoding="utf-8",
    )

    params_path = gold / "dixon_coles_params.json"
    params_path.write_text(json.dumps(_PARAMS_DICT), encoding="utf-8")

    return {"features": features, "history": history, "params": params_path}


def _make_ko_csv(tmp_path: Path) -> Path:
    """Crea CSV de llaves sintetico en tmp_path."""
    ko_dir = tmp_path / "data" / "knockouts"
    ko_dir.mkdir(parents=True, exist_ok=True)
    ko_csv = ko_dir / "r32_fixtures.csv"
    ko_csv.write_text(_KO_CSV_CONTENT, encoding="utf-8")
    return ko_csv


def _write_apptest_inputs(tmp_path: Path, ko_csv: Path) -> dict[str, Path]:
    """Crea todos los insumos necesarios para AppTest con pestaña Knockouts."""
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
    """Inyecta rutas sinteticas en los modulos de la app (monkeypatch)."""
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

    # CSV de llaves sintetico
    monkeypatch.setattr(ko_mod, "DEFAULT_KO_CSV", paths["ko_csv"])
    # player_factor no existe → degradacion elegante (R2); lo dejamos ausente en R4


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


# ---------------------------------------------------------------------------
# R1 — Mercados de goles presentes por llave
# ---------------------------------------------------------------------------


def test_mercados_presentes_por_llave(tmp_path: Path) -> None:
    """R1: _compute_analisis_data retorna MarketSummary con O/U totales y BTTS."""
    from src.app.tabs.knockouts import _compute_analisis_data

    params = _make_synthetic_params()
    _compute_analisis_data.clear()

    # path de player_factor ausente → solo mercados (sin goleadores)
    data = _compute_analisis_data(params, "ARG", "BRA", str(tmp_path / "no_pf.csv"))

    assert data["error"] is None, f"Error inesperado: {data['error']}"

    summary = data["summary"]
    assert summary is not None, "summary no debe ser None cuando los equipos existen en params"

    # O/U totales (>=1 linea)
    assert len(summary.totals) > 0, "summary.totals esta vacio"
    for ml in summary.totals:
        assert 0.0 <= ml.over <= 1.0, f"over fuera de rango: {ml.over}"
        assert 0.0 <= ml.under <= 1.0, f"under fuera de rango: {ml.under}"
        assert abs(ml.over + ml.under - 1.0) < 1e-9, "over + under != 1"

    # BTTS
    assert 0.0 <= summary.btts_yes <= 1.0
    assert abs(summary.btts_yes + summary.btts_no - 1.0) < 1e-9, "btts_yes + btts_no != 1"

    # Totales por equipo
    assert len(summary.home_totals) > 0, "summary.home_totals esta vacio"
    assert len(summary.away_totals) > 0, "summary.away_totals esta vacio"


# ---------------------------------------------------------------------------
# R2 — Goleadores anytime top-K por equipo
# ---------------------------------------------------------------------------


def test_goleadores_top_k_por_equipo(tmp_path: Path) -> None:
    """R2: _compute_analisis_data retorna top-3 anytime-scorers por equipo con player_factor."""
    from src.app.tabs.knockouts import _compute_analisis_data

    params = _make_synthetic_params()
    pf_path = _make_player_factor(tmp_path)
    _compute_analisis_data.clear()

    data = _compute_analisis_data(params, "ARG", "BRA", str(pf_path), top_k=3)

    assert data["error"] is None
    assert not data["no_player_factor"], "player_factor existe pero no_player_factor=True"

    scorers_home = data["scorers_home"]
    scorers_away = data["scorers_away"]

    assert scorers_home is not None, "scorers_home no debe ser None"
    assert scorers_away is not None, "scorers_away no debe ser None"
    assert 1 <= len(scorers_home) <= 3, f"scorers_home len={len(scorers_home)}, esperado 1-3"
    assert 1 <= len(scorers_away) <= 3, f"scorers_away len={len(scorers_away)}, esperado 1-3"

    for s in scorers_home:
        assert 0.0 < s.prob_score <= 1.0, f"prob_score={s.prob_score} fuera de (0, 1]"
    for s in scorers_away:
        assert 0.0 < s.prob_score <= 1.0, f"prob_score={s.prob_score} fuera de (0, 1]"


def test_sin_player_factor_degrada(tmp_path: Path) -> None:
    """R2: sin player_factor.csv -> no_player_factor=True, mercados siguen, sin excepcion."""
    from src.app.tabs.knockouts import _compute_analisis_data

    params = _make_synthetic_params()
    _compute_analisis_data.clear()

    data = _compute_analisis_data(params, "ARG", "BRA", str(tmp_path / "no_existe.csv"))

    assert data["error"] is None, f"Excepcion inesperada en degradacion: {data['error']}"
    assert data["no_player_factor"] is True, "no_player_factor debe ser True sin el archivo"
    # Mercados deben seguir disponibles (no dependen de player_factor)
    assert data["summary"] is not None, "summary debe estar disponible sin player_factor"
    assert len(data["summary"].totals) > 0, "O/U totales deben estar disponibles"


# ---------------------------------------------------------------------------
# R3 — Etiqueta v1 presente + cache eficiente
# ---------------------------------------------------------------------------


def test_etiqueta_v1_presente(tmp_path: Path) -> None:
    """R3: _render_analisis_llave llama st.caption con texto que menciona 'v1'."""
    import unittest.mock as mock
    from src.app.tabs.knockouts import _render_analisis_llave, _compute_analisis_data

    params = _make_synthetic_params()
    _compute_analisis_data.clear()

    captions_shown: list[str] = []

    mock_expander = mock.MagicMock()
    mock_expander.__enter__ = mock.MagicMock(return_value=mock_expander)
    mock_expander.__exit__ = mock.MagicMock(return_value=False)

    with (
        mock.patch("streamlit.expander", return_value=mock_expander),
        mock.patch("streamlit.caption", side_effect=lambda x, **kw: captions_shown.append(str(x))),
        mock.patch("streamlit.markdown"),
        mock.patch("streamlit.write"),
    ):
        _render_analisis_llave(params, "ARG", "BRA", tmp_path / "no_pf.csv")

    assert any("v1" in c for c in captions_shown), (
        f"Etiqueta 'v1' no encontrada en captions: {captions_shown}"
    )


def test_cache_no_recalcula_por_slider(tmp_path: Path) -> None:
    """R3: mismos (home, away, path) no recalculan el panel al mover el slider gamma.

    Simula dos re-renders del tab (como al mover el slider): los args de
    _compute_analisis_data son identicos → cache hit → cuerpo ejecutado solo 1 vez.
    """
    import unittest.mock as mock
    from src.app.tabs.knockouts import _compute_analisis_data
    from src.markets.goals import market_summary as real_market_summary

    params = _make_synthetic_params()
    _compute_analisis_data.clear()

    call_count: dict[str, int] = {"n": 0}

    def spy_market(p, h, a, **kwargs):
        call_count["n"] += 1
        return real_market_summary(p, h, a, **kwargs)

    pf_str = str(tmp_path / "no_pf.csv")

    with mock.patch("src.app.tabs.knockouts.market_summary", spy_market):
        # Primera llamada: cache miss → cuerpo ejecutado
        _compute_analisis_data(params, "ARG", "BRA", pf_str)
        # Segunda llamada con mismos (home, away, path): cache hit → cuerpo NO ejecutado
        _compute_analisis_data(params, "ARG", "BRA", pf_str)

    assert call_count["n"] == 1, (
        f"market_summary se llamó {call_count['n']} veces con mismos args; "
        "la cache debería reducirlo a 1 (mover slider gamma no debe recalcular el panel v1)"
    )


# ---------------------------------------------------------------------------
# R4 — Integración sin regresión (AppTest)
# ---------------------------------------------------------------------------


def test_render_knockouts_no_excepciona_con_analisis(
    tmp_path: Path, monkeypatch
) -> None:
    """R4: render_knockouts con panel de analisis integrado no lanza excepcion.

    Degrada elegantemente sin player_factor (R2): el tab sigue funcionando.
    """
    ko_csv = _make_ko_csv(tmp_path)
    paths = _write_apptest_inputs(tmp_path, ko_csv)

    at = _get_app(monkeypatch, paths)
    assert not at.exception, f"AppTest lanzo excepcion: {at.exception}"


def test_otras_pestanas_intactas(tmp_path: Path, monkeypatch) -> None:
    """R4: las cuatro pestanas (Calendario, Selecciones, Modelo, Knockouts) siguen presentes.

    El panel de analisis Feature 20 no rompe las pestanas existentes ni el 1X2/P(avanza).
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
