"""R12–R19 — ratings Elo por selección (offline, DataFrames en memoria)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.features.elo import (
    EloParams,
    HISTORY_COLUMNS,
    expected_home,
    k_for_tournament,
    margin_multiplier,
    ratings_as_of,
    run_elo,
)


def _m(date, mid, home, away, hg, ag, tournament="Friendly", neutral=True):
    return {
        "date": date,
        "match_id": mid,
        "home_code": home,
        "away_code": away,
        "home_goals": hg,
        "away_goals": ag,
        "tournament": tournament,
        "neutral": neutral,
    }


def _df(matches):
    return pd.DataFrame(matches)


def test_rating_inicial_1500():
    # R12: primera aparición → rating inicial 1500; parametrizable vía EloParams.
    df = _df([_m("2025-01-01", "a", "ARG", "BRA", 1, 0)])
    _, history = run_elo(df)
    assert (history["elo_pre"] == 1500.0).all()

    _, history_custom = run_elo(df, EloParams(initial=1600.0))
    assert (history_custom["elo_pre"] == 1600.0).all()


def test_actualizacion_victoria_empate_derrota():
    # R13: elo_post = elo_pre + K·G·(score − We); gana sube, pierde baja; en el empate
    # sube el de menor expectativa We y baja el de mayor.
    # Victoria del local (neutral, ratings iguales): local sube, visitante baja.
    ratings, _ = run_elo(_df([_m("2025-01-01", "a", "ARG", "BRA", 1, 0)]))
    assert ratings["ARG"] > 1500.0 and ratings["BRA"] < 1500.0

    # Derrota del local: local baja, visitante sube.
    ratings, _ = run_elo(_df([_m("2025-01-01", "a", "ARG", "BRA", 0, 1)]))
    assert ratings["ARG"] < 1500.0 and ratings["BRA"] > 1500.0

    # Empate con expectativas desiguales (localía no neutral → We_home > 0.5):
    # el local (mayor We) baja y el visitante (menor We) sube.
    ratings, history = run_elo(
        _df([_m("2025-01-01", "a", "MEX", "JPN", 1, 1, neutral=False)])
    )
    assert history.iloc[0]["we"] > 0.5  # expectativa del local con +100
    assert ratings["MEX"] < 1500.0 and ratings["JPN"] > 1500.0


def test_k_por_torneo_configurable():
    # R14: K por importancia del torneo; precedencia eliminatoria (50) sobre Mundial (60).
    assert k_for_tournament("FIFA World Cup qualification") == 50.0
    assert k_for_tournament("FIFA World Cup") == 60.0
    assert k_for_tournament("UEFA Nations League") == 40.0
    assert k_for_tournament("FIFA Confederations Cup") == 40.0
    assert k_for_tournament("Copa América") == 50.0  # continental
    assert k_for_tournament("Gold Cup") == 50.0
    assert k_for_tournament("Friendly") == 20.0  # fuente pública
    assert k_for_tournament("Friendlies") == 20.0  # API-Football
    assert k_for_tournament("Torneo Inventado") == 30.0  # default

    # Mapa configurable sin tocar el algoritmo.
    params = EloParams(k_rules=((("mi copa",), 99.0),), default_k=11.0)
    assert k_for_tournament("Mi Copa 2026", params) == 99.0
    assert k_for_tournament("FIFA World Cup", params) == 11.0


def test_multiplicador_margen_g():
    # R15: diff <= 1 → 1.0; diff == 2 → 1.5; diff >= 3 → (11 + diff) / 8.
    assert margin_multiplier(0, 0) == 1.0
    assert margin_multiplier(1, 0) == 1.0
    assert margin_multiplier(2, 0) == 1.5
    assert margin_multiplier(1, 3) == 1.5  # valor absoluto del margen
    assert margin_multiplier(3, 0) == (11 + 3) / 8  # 1.75
    assert margin_multiplier(5, 0) == (11 + 5) / 8  # 2.0


def test_ventaja_localia_solo_no_neutral():
    # R16: dr = elo_home − elo_away + 100 si neutral=False; sin el +100 si neutral=True.
    assert expected_home(1500.0, 1500.0, neutral=True) == 0.5
    con_localia = expected_home(1500.0, 1500.0, neutral=False)
    assert con_localia == pytest.approx(1.0 / (1.0 + 10.0 ** (-100.0 / 400.0)))
    assert con_localia > 0.5
    # El valor 100 es parametrizable.
    params = EloParams(home_advantage=0.0)
    assert expected_home(1500.0, 1500.0, neutral=False, params=params) == 0.5


def test_simetria_suma_cambios_cero():
    # R17: la suma de los cambios de rating de ambos equipos es exactamente 0.
    df = _df(
        [
            _m("2025-01-01", "a", "ARG", "BRA", 3, 0, tournament="FIFA World Cup", neutral=False),
            _m("2025-01-05", "b", "BRA", "ARG", 2, 2, tournament="Friendly", neutral=False),
            _m("2025-01-09", "c", "ARG", "ESP", 0, 1, tournament="Copa América", neutral=True),
        ]
    )
    _, history = run_elo(df)
    for i in range(0, len(history), 2):
        delta_home = history.iloc[i]["elo_post"] - history.iloc[i]["elo_pre"]
        delta_away = history.iloc[i + 1]["elo_post"] - history.iloc[i + 1]["elo_pre"]
        assert delta_home + delta_away == 0.0  # exacto, no aproximado
        assert history.iloc[i]["we"] + history.iloc[i + 1]["we"] == 1.0
        assert history.iloc[i]["score"] + history.iloc[i + 1]["score"] == 1.0
        assert history.iloc[i]["k"] == history.iloc[i + 1]["k"]  # mismo K
        assert history.iloc[i]["g"] == history.iloc[i + 1]["g"]  # mismo G


def test_orden_cronologico_determinista():
    # R18: orden (date, match_id) ascendente con desempate determinista; dos ejecuciones
    # (incluso con el input permutado) → exactamente el mismo historial y ratings.
    matches = [
        _m("2025-01-05", "z", "ARG", "ESP", 0, 2),
        _m("2025-01-01", "b", "ARG", "FRA", 1, 1),  # misma fecha que "a": desempata match_id
        _m("2025-01-01", "a", "ARG", "BRA", 2, 0),
    ]
    df = _df(matches)
    ratings_1, history_1 = run_elo(df)
    ratings_2, history_2 = run_elo(df.iloc[::-1].reset_index(drop=True))

    assert ratings_1 == ratings_2
    pd.testing.assert_frame_equal(history_1, history_2)
    # En la misma fecha procesa primero match_id "a" (ARG-BRA) y después "b" (ARG-FRA).
    assert history_1.iloc[0]["opponent_code"] == "BRA"
    assert history_1.iloc[2]["opponent_code"] == "FRA"
    assert list(history_1["date"]) == sorted(history_1["date"])


def test_elo_global_incluye_fuera_de_48():
    # R19: el Elo se calcula sobre TODOS los partidos de silver, incluidos los de
    # equipos fuera de las 48 (códigos slug), con historial por equipo y partido.
    df = _df(
        [
            _m("2025-01-01", "a", "wales", "ARG", 0, 2),
            _m("2025-01-05", "b", "finland", "wales", 1, 1),
        ]
    )
    ratings, history = run_elo(df)

    assert list(history.columns) == list(HISTORY_COLUMNS)
    assert len(history) == 4  # 2 filas por partido
    assert {"wales", "finland", "ARG"} <= set(ratings)
    assert ratings["wales"] < 1500.0  # perdió contra ARG y empató después
    # Rating vigente con replay date < as_of_date (estrictamente anterior).
    vigentes = ratings_as_of(history, "2025-01-05")
    assert vigentes["wales"] == history.iloc[0]["elo_post"]  # solo el primer partido
    assert "finland" not in vigentes  # sin partidos previos a la fecha
