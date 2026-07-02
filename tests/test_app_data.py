"""Tests de src/app/data.py — capa de datos pura (R1–R7, R9–R13).

100 % offline y deterministas: insumos sinteticos en tmp_path, cero red,
cero reloj, cero entrenamientos (fit_dixon_coles jamas se invoca).
Mismo estilo de fixtures que tests/test_dashboard.py.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Datos de fixture compartidos
# ---------------------------------------------------------------------------

AS_OF = "2025-12-01"

FEATURES_HEADER = (
    "code,as_of_date,matches_count,gf_ma15,ga_ma15,corners_for_ma15,"
    "corners_against_ma15,cards_ma15,shots_ma15,shots_on_target_ma15,"
    "possession_ma15,elo"
)

# (code, matches_count, gf_ma15, ga_ma15, elo)
FEATURES_ROWS = (
    ("ARG", 15, "2.1", "0.8", 2100.0),
    ("BRA", 15, "1.9", "0.9", 2050.0),
    ("FRA", 12, "1.8", "1.0", 2000.0),
    ("JPN", 0, "", "", 1500.0),
    ("MEX", 15, "1.5", "1.1", 1800.0),
    ("USA", 14, "1.4", "1.2", 1750.0),
)

HISTORY_HEADER = "date,code,opponent_code,elo_pre,elo_post,k,g,we,score"
HISTORY_ROWS = (
    "2025-10-01,ARG,BRA,2080.0,2090.0,35.0,1.0,0.55,1.0",
    "2025-10-01,BRA,ARG,2040.0,2030.0,35.0,1.0,0.45,0.0",
    "2025-10-05,MEX,USA,1790.0,1800.0,35.0,1.0,0.5,1.0",
    "2025-10-05,USA,MEX,1760.0,1750.0,35.0,1.0,0.5,0.0",
    "2025-11-01,ARG,MEX,2090.0,2100.0,35.0,1.0,0.6,1.0",
    "2025-11-01,MEX,ARG,1800.0,1790.0,35.0,1.0,0.4,0.0",
)

RESULTS_HEADER = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral"

# 1 jugado + 2 pendientes WC2026 + 1 partido Mundial pasado (2022) + 1 pendiente NO WC + 1 fila malformada
RESULTS_ROWS: tuple[str, ...] = (
    "2022-12-18,Argentina,France,3,3,FIFA World Cup,Lusail,Qatar,FALSE",  # Mundial pasado — debe excluirse
    "2026-06-01,France,Brazil,2,1,FIFA World Cup,Paris,France,FALSE",
    "2026-06-11,Mexico,Argentina,NA,NA,FIFA World Cup,Mexico City,Mexico,FALSE",
    "2026-06-12,Brazil,Japan,NA,NA,FIFA World Cup,Toronto,Canada,TRUE",
    "2026-06-13,Mexico,Brazil,NA,NA,Friendly,Dallas,United States,TRUE",
    "2026-06-14,solo-dos-columnas",
)


def make_params(success: bool = True) -> dict:
    """Params JSON con el contrato de la feature 3."""
    return {
        "as_of_date": AS_OF,
        "from_date": "2018-01-01",
        "xi": 0.65,
        "mu": 0.1,
        "home_advantage": 0.3,
        "rho": -0.08,
        "attack": {
            "ARG": 0.40, "BRA": 0.15, "FRA": 0.25, "JPN": -0.30,
            "MEX": 0.20, "USA": 0.10, "andorra": -0.80,
        },
        "defense": {
            "ARG": 0.30, "BRA": 0.20, "FRA": 0.10, "JPN": -0.40,
            "MEX": 0.05, "USA": 0.00, "andorra": -0.60,
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
    """Insumos sinteticos en base con el layout real (data/gold, data/bronze)."""
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

    params = gold / "dixon_coles_params.json"
    params.write_text(json.dumps(make_params(success)), encoding="utf-8")

    results = base / "data" / "bronze" / "public_results" / "results.csv"
    if with_results:
        results.parent.mkdir(parents=True, exist_ok=True)
        rows = RESULTS_ROWS if results_rows is None else results_rows
        results.write_text("\n".join([RESULTS_HEADER, *rows]) + "\n", encoding="utf-8")

    return {
        "features": features,
        "history": history,
        "params": params,
        "results": results,
    }


# ---------------------------------------------------------------------------
# R1 — rutas inyectadas (tmp_path)
# ---------------------------------------------------------------------------


def test_rutas_inyectadas_tmp_path(tmp_path: Path) -> None:
    """R1: load_app_data con rutas inyectadas usa exclusivamente esas rutas."""
    from src.app.data import load_app_data

    paths = write_inputs(tmp_path)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    # verifica que los datos vienen de las rutas sinteticas
    codes = {r["code"] for r in app_data.features_rows}
    assert codes == {"ARG", "BRA", "FRA", "JPN", "MEX", "USA"}
    assert app_data.params.as_of_date == AS_OF
    assert app_data.bronze_disponible is True


# ---------------------------------------------------------------------------
# R2 — errores accionables ante insumos criticos ausentes
# ---------------------------------------------------------------------------


def _call_load(paths: dict) -> None:
    """Helper: llama load_app_data con los paths del dict de write_inputs."""
    from src.app.data import load_app_data

    load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )


def test_falta_gold_error_accionable(tmp_path: Path) -> None:
    """R2: falta features.csv o history.csv → AppInputError con ruta y build-features."""
    from src.app.data import AppInputError

    paths = write_inputs(tmp_path / "a")
    paths["features"].unlink()
    with pytest.raises(AppInputError) as exc:
        _call_load(paths)
    msg = str(exc.value)
    assert str(paths["features"]) in msg
    assert "build-features" in msg
    assert "python -m" in msg

    paths2 = write_inputs(tmp_path / "b")
    paths2["history"].unlink()
    with pytest.raises(AppInputError) as exc2:
        _call_load(paths2)
    assert str(paths2["history"]) in str(exc2.value)
    assert "build-features" in str(exc2.value)


def test_params_invalidos_error_accionable(tmp_path: Path) -> None:
    """R2: params ausentes o sin contrato → AppInputError con 'train'."""
    from src.app.data import AppInputError

    paths = write_inputs(tmp_path)
    paths["params"].unlink()
    with pytest.raises(AppInputError) as exc:
        _call_load(paths)
    msg = str(exc.value)
    assert "train" in msg
    assert "python -m" in msg

    # JSON sin las claves del contrato → mismo error
    paths["params"].write_text('{"foo": 1}', encoding="utf-8")
    with pytest.raises(AppInputError) as exc2:
        _call_load(paths)
    assert "train" in str(exc2.value)


# ---------------------------------------------------------------------------
# R3 — degradacion parcial sin bronze
# ---------------------------------------------------------------------------


def test_sin_bronze_degradacion(tmp_path: Path) -> None:
    """R3: sin results.csv → bronze_disponible=False, matches vacio, no falla."""
    from src.app.data import load_app_data

    paths = write_inputs(tmp_path, with_results=False)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    assert app_data.bronze_disponible is False
    assert len(app_data.matches) == 0
    # gold sigue disponible
    assert len(app_data.features_rows) > 0
    assert len(app_data.history_rows) > 0


# ---------------------------------------------------------------------------
# R4 — data.py no importa streamlit ni modulos de red
# ---------------------------------------------------------------------------


def test_data_no_importa_streamlit_ni_red(tmp_path: Path) -> None:
    """R4: src.app.data no importa streamlit ni modulos de red directamente.

    Verifica el codigo fuente del modulo: no debe contener imports de streamlit,
    src.ingestion.client, src.ingestion.config ni src.ingestion.ingest.
    Ademas, al reimportar desde cero, streamlit no debe aparecer en sys.modules
    como consecuencia directa del import de data.py.
    """
    import inspect

    # verificacion por inspeccion de codigo fuente
    import src.app.data as data_mod

    source = inspect.getsource(data_mod)
    # verifica que no haya sentencias import de los modulos prohibidos
    assert "import streamlit" not in source, "data.py importa streamlit"
    assert "from ..ingestion.client" not in source, "data.py importa ingestion.client"
    assert "import ingestion.client" not in source
    assert "from ..ingestion.config" not in source, "data.py importa ingestion.config"
    assert "from ..ingestion.ingest" not in source, "data.py importa ingestion.ingest"
    assert "import src.ingestion.client" not in source

    # verificacion de que el import de data.py no arrastra streamlit a sys.modules
    streamlit_antes = {k for k in sys.modules if "streamlit" in k}

    for mod in list(sys.modules.keys()):
        if "src.app" in mod:
            sys.modules.pop(mod, None)

    importlib.import_module("src.app.data")

    streamlit_despues = {k for k in sys.modules if "streamlit" in k}
    nuevos_streamlit = streamlit_despues - streamlit_antes
    assert not nuevos_streamlit, f"data.py introdujo streamlit en sys.modules: {nuevos_streamlit}"


# ---------------------------------------------------------------------------
# R5 — clasificacion jugado/pendiente sin reloj y agrupacion por dia
# ---------------------------------------------------------------------------


def test_clasificacion_jugado_pendiente_sin_reloj(tmp_path: Path) -> None:
    """R5: jugado = ambos scores convertibles a int; pendiente = no convertible."""
    from src.app.data import load_app_data

    paths = write_inputs(tmp_path)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    wc_matches = app_data.matches
    # solo partidos FIFA World Cup
    jugados = [m for m in wc_matches if m.played]
    pendientes = [m for m in wc_matches if not m.played]

    # fixture: 1 jugado (France vs Brazil 2-1) y 2 pendientes (MEX-ARG, BRA-JPN)
    assert len(jugados) == 1
    assert len(pendientes) == 2
    j = jugados[0]
    assert j.home_score == 2
    assert j.away_score == 1
    # friendly y malformada no deben estar
    assert all(m.home_name != "Mexico" or m.away_name != "Brazil" for m in wc_matches)


def test_calendario_excluye_mundiales_pasados(tmp_path: Path) -> None:
    """R5: partidos WC con date < WC2026_FROM_DATE deben quedar excluidos del calendario.

    El fixture incluye el partido Argentina-France 2022-12-18 (final Qatar 2022).
    Ese partido NO debe aparecer en matches aunque su tournament sea 'FIFA World Cup'.
    Solo los partidos de 2026 (date >= '2026-01-01') deben estar presentes.
    """
    from src.app.data import WC2026_FROM_DATE, load_app_data

    paths = write_inputs(tmp_path)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    # ninguna fecha debe ser anterior a WC2026_FROM_DATE
    for m in app_data.matches:
        assert m.date >= WC2026_FROM_DATE, (
            f"Partido con date={m.date!r} ({m.home_name} vs {m.away_name}) "
            f"no deberia aparecer: es de un Mundial anterior al WC2026."
        )
    # el partido de 2022 especificamente no debe estar
    pasado = [m for m in app_data.matches if m.date == "2022-12-18"]
    assert pasado == [], f"Partido del Qatar 2022 encontrado: {pasado}"
    # los partidos de 2026 si deben estar
    wc2026 = [m for m in app_data.matches if m.date >= "2026-01-01"]
    assert len(wc2026) == 3, f"Esperados 3 partidos WC2026, encontrados {len(wc2026)}"


def test_agrupacion_y_orden_por_dia(tmp_path: Path) -> None:
    """R5: partidos ordenados ascendente por (date, home_team, away_team)."""
    from src.app.data import load_app_data

    paths = write_inputs(tmp_path)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    dates = [m.date for m in app_data.matches]
    assert dates == sorted(dates)


def test_dia_default(tmp_path: Path) -> None:
    """R5: pending_default_day devuelve el primer dia con pendiente; si no hay, el ultimo."""
    from src.app.data import load_app_data, pending_default_day

    paths = write_inputs(tmp_path)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    day = pending_default_day(app_data.matches)
    # primer dia con pendiente es 2026-06-11 (MEX-ARG)
    assert day == "2026-06-11"

    # sin pendientes → ultimo dia con partidos
    solo_jugado_rows = (
        "2026-06-01,France,Brazil,2,1,FIFA World Cup,Paris,France,FALSE",
        "2026-06-05,Mexico,Argentina,3,0,FIFA World Cup,Dallas,US,FALSE",
    )
    paths2 = write_inputs(tmp_path / "sub", results_rows=solo_jugado_rows)
    app_data2 = load_app_data(
        features_csv=paths2["features"],
        elo_history_csv=paths2["history"],
        params_path=paths2["params"],
        results_csv=paths2["results"],
    )
    day2 = pending_default_day(app_data2.matches)
    assert day2 == "2026-06-05"

    # sin partidos → None
    paths3 = write_inputs(tmp_path / "sub2", with_results=False)
    app_data3 = load_app_data(
        features_csv=paths3["features"],
        elo_history_csv=paths3["history"],
        params_path=paths3["params"],
        results_csv=paths3["results"],
    )
    assert pending_default_day(app_data3.matches) is None


# ---------------------------------------------------------------------------
# R6 — prediccion pendiente con modelo real
# ---------------------------------------------------------------------------


def test_prediccion_pendiente_modelo_real(tmp_path: Path) -> None:
    """R6: predict_for devuelve probabilidades 1X2 reales (no mock)."""
    from src.app.data import WcMatch, load_app_data, predict_for
    from src.models.dixon_coles import load_params, predict_match

    paths = write_inputs(tmp_path)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    pendientes = [m for m in app_data.matches if not m.played and m.predecible]
    assert len(pendientes) >= 1

    match = pendientes[0]
    pred = predict_for(match, app_data.params)
    assert pred is not None

    # compara con load_params + predict_match directo
    params_real = load_params(paths["params"])
    pred_ref = predict_match(params_real, match.home_code, match.away_code)
    assert abs(pred.prob_home - pred_ref.prob_home) < 1e-9
    assert abs(pred.prob_draw - pred_ref.prob_draw) < 1e-9
    assert abs(pred.prob_away - pred_ref.prob_away) < 1e-9


# ---------------------------------------------------------------------------
# R7 — evaluacion de partido jugado: acierto y fallo
# ---------------------------------------------------------------------------


def test_outcome_eval_acierto_y_fallo(tmp_path: Path) -> None:
    """R7: match_outcome_eval calcula desenlace, probabilidad y acierto correctamente."""
    from src.app.data import load_app_data, match_outcome_eval, predict_for

    paths = write_inputs(tmp_path)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    jugados = [m for m in app_data.matches if m.played and m.predecible]
    assert len(jugados) >= 1

    match = jugados[0]
    pred = predict_for(match, app_data.params)
    assert pred is not None

    eval_result = match_outcome_eval(match, pred)
    # desenlace real debe ser 1, X o 2
    assert eval_result.outcome in ("1", "X", "2")
    # probabilidad asignada debe ser la del desenlace real
    if eval_result.outcome == "1":
        assert abs(eval_result.prob_outcome - pred.prob_home) < 1e-9
    elif eval_result.outcome == "X":
        assert abs(eval_result.prob_outcome - pred.prob_draw) < 1e-9
    else:
        assert abs(eval_result.prob_outcome - pred.prob_away) < 1e-9

    # acierto: desenlace real == argmax 1X2 con desempate (1, X, 2)
    probs = {"1": pred.prob_home, "X": pred.prob_draw, "2": pred.prob_away}
    best = max(probs, key=lambda k: (probs[k], ["1", "X", "2"].index(k) * -1 + 2))
    # desempate determinista por orden (1, X, 2): mayor prob gana; empate → el primero
    order = ["1", "X", "2"]
    best_det = max(order, key=lambda k: (probs[k], -order.index(k)))
    assert eval_result.acierto == (eval_result.outcome == best_det)


# ---------------------------------------------------------------------------
# R9 — partido sin alias FIFA no predecible, no aborta
# ---------------------------------------------------------------------------


def test_partido_sin_alias_no_predecible(tmp_path: Path) -> None:
    """R9: equipo sin alias -> WcMatch.predecible=False; el resto del lote continua."""
    from src.app.data import load_app_data

    rows = RESULTS_ROWS + (
        "2026-06-15,Atlantis,Argentina,NA,NA,FIFA World Cup,Nowhere,Nowhere,FALSE",
    )
    paths = write_inputs(tmp_path, results_rows=rows)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    no_pred = [m for m in app_data.matches if not m.predecible]
    pred = [m for m in app_data.matches if m.predecible]
    assert len(no_pred) >= 1
    atlantis_match = next(m for m in no_pred if m.home_name == "Atlantis")
    assert atlantis_match is not None
    # el resto sigue siendo predecible
    assert len(pred) >= 2


# ---------------------------------------------------------------------------
# R10 — team_profile: ficha de equipo
# ---------------------------------------------------------------------------


def test_team_profile_completo(tmp_path: Path) -> None:
    """R10: team_profile devuelve datos consistentes para un equipo con datos."""
    from src.app.data import load_app_data, team_profile

    paths = write_inputs(tmp_path)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    profile = team_profile("ARG", app_data)
    assert profile.code == "ARG"
    assert profile.elo is not None
    assert profile.history_rows  # ARG tiene historial
    assert profile.matches  # ARG tiene partidos WC2026


def test_team_profile_sin_historial(tmp_path: Path) -> None:
    """R10: equipo con matches_count=0 (JPN sin historial) no falla."""
    from src.app.data import load_app_data, team_profile

    paths = write_inputs(tmp_path)
    app_data = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    profile = team_profile("JPN", app_data)
    assert profile.code == "JPN"
    assert profile.matches_count == 0
    # sin crash aunque no tenga historial Elo extenso


# ---------------------------------------------------------------------------
# R12 — determinismo y sin reloj
# ---------------------------------------------------------------------------


def test_determinismo_misma_entrada(tmp_path: Path) -> None:
    """R12: misma entrada → mismas matches, mismo orden, mismas probabilidades."""
    from src.app.data import load_app_data, predict_for

    paths = write_inputs(tmp_path)
    app_data1 = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    app_data2 = load_app_data(
        features_csv=paths["features"],
        elo_history_csv=paths["history"],
        params_path=paths["params"],
        results_csv=paths["results"],
    )
    assert len(app_data1.matches) == len(app_data2.matches)
    for m1, m2 in zip(app_data1.matches, app_data2.matches):
        assert m1.date == m2.date
        assert m1.home_name == m2.home_name
        assert m1.away_name == m2.away_name

    # predicciones deterministas
    pendientes1 = [m for m in app_data1.matches if not m.played and m.predecible]
    pendientes2 = [m for m in app_data2.matches if not m.played and m.predecible]
    for m1, m2 in zip(pendientes1, pendientes2):
        p1 = predict_for(m1, app_data1.params)
        p2 = predict_for(m2, app_data2.params)
        assert p1 is not None and p2 is not None
        assert abs(p1.prob_home - p2.prob_home) < 1e-9


def test_sin_reloj_en_fuente(tmp_path: Path) -> None:
    """R12: la fuente de clasificacion es el dataset (scores), no datetime.now()."""
    import inspect

    import src.app.data as data_mod

    source = inspect.getsource(data_mod)
    # el modulo no debe usar datetime.now() ni date.today() ni RNG
    assert "datetime.now()" not in source
    assert "date.today()" not in source
    assert "random" not in source


# ---------------------------------------------------------------------------
# R13 — import sin efectos de disco/red
# ---------------------------------------------------------------------------


def test_import_app_sin_efectos(tmp_path: Path, monkeypatch) -> None:
    """R13: importar src.app no dispara lecturas de disco, red ni escritura."""
    import os

    # Monkeypatch el directorio de trabajo para que cualquier lectura relativa
    # desde cwd falle si intentara leer desde la ruta real del proyecto
    monkeypatch.chdir(tmp_path)  # directorio vacio: sin data/

    for mod in list(sys.modules.keys()):
        if "src.app" in mod:
            sys.modules.pop(mod, None)

    # importar sin que explote (no hay data/ en tmp_path)
    importlib.import_module("src.app")
    importlib.import_module("src.app.data")

    # el directorio sigue vacio: no se escribio nada
    assert list(tmp_path.iterdir()) == []
