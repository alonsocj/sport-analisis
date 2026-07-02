"""Tests de persistencia y predicción del modelo Dixon-Coles (R11–R18) — feature 3.

100 % offline y deterministas: silver sintético en ``tmp_path`` (helper compartido
de ``tests/test_dixon_coles_fit.py``), semillas fijas, cero red, cero ``now()``
implícito, cero ``API_FOOTBALL_KEY``.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.models.dixon_coles import (
    DCConfig,
    DixonColesParams,
    NotFittedError,
    UnknownTeamError,
    fit_dixon_coles,
    load_params,
    predict_match,
    save_params,
    score_matrix,
)
from tests.test_dixon_coles_fit import AS_OF, make_round_robin_rows, write_contract_silver

# Claves mínimas del contrato JSON (R11, design.md).
CONTRACT_KEYS = {
    "as_of_date",
    "from_date",
    "xi",
    "mu",
    "home_advantage",
    "rho",
    "attack",
    "defense",
    "n_matches",
    "convergencia",
}


@pytest.fixture(scope="module")
def fitted_params(tmp_path_factory: pytest.TempPathFactory) -> DixonColesParams:
    """Parámetros ajustados sobre silver sintético pequeño (4 equipos, 24 partidos)."""
    tmp = tmp_path_factory.mktemp("dc_predict")
    silver = write_contract_silver(
        tmp, make_round_robin_rows(("AAA", "BBB", "CCC", "DDD"), rounds=2, seed=11)
    )
    return fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig())


def manual_params(
    mu: float = 0.1, gamma: float = 0.3, rho: float = -0.08
) -> DixonColesParams:
    """Parámetros construidos a mano (deterministas) con anfitrionas y no anfitrionas."""
    attack = {"MEX": 0.20, "USA": 0.10, "CAN": 0.00, "ARG": 0.40, "BRA": -0.10, "JPN": -0.60}
    defense = {"MEX": 0.05, "USA": 0.00, "CAN": -0.05, "ARG": 0.30, "BRA": 0.20, "JPN": -0.50}
    return DixonColesParams(
        as_of_date="2026-06-01",
        from_date="2018-01-01",
        xi=0.65,
        mu=mu,
        home_advantage=gamma,
        rho=rho,
        attack=attack,
        defense=defense,
        n_matches=240,
        n_teams=6,
        min_matches=5,
        reg_lambda=1.0,
        low_data_teams=[],
        convergencia={"success": True, "n_iter": 50, "message": "ok", "neg_log_lik": 100.0},
    )


# ---------------------------------------------------------------------------
# R11 — serialización JSON round-trip
# ---------------------------------------------------------------------------


def test_json_contiene_claves_contrato(fitted_params: DixonColesParams, tmp_path: Path) -> None:
    """R11: el JSON persistido contiene al menos las claves del contrato."""
    path = save_params(fitted_params, tmp_path / "gold" / "dixon_coles_params.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert CONTRACT_KEYS <= set(data)
    # refinamientos de design.md también presentes
    assert {"n_teams", "min_matches", "reg_lambda", "low_data_teams"} <= set(data)
    assert isinstance(data["attack"], dict) and isinstance(data["defense"], dict)
    assert all(isinstance(v, float) for v in data["attack"].values())
    assert data["as_of_date"] == AS_OF


def test_round_trip_json_parametros(fitted_params: DixonColesParams, tmp_path: Path) -> None:
    """R11: guardar → cargar devuelve parámetros idénticos (sin reentrenar)."""
    path = save_params(fitted_params, tmp_path / "params.json")
    cargado = load_params(path)
    assert cargado == fitted_params  # igualdad campo a campo (floats exactos)


def test_prediccion_identica_tras_cargar(fitted_params: DixonColesParams, tmp_path: Path) -> None:
    """R11: los parámetros cargados producen EXACTAMENTE las mismas predicciones."""
    path = save_params(fitted_params, tmp_path / "params.json")
    cargado = load_params(path)
    pred_a = predict_match(fitted_params, "AAA", "BBB")
    pred_b = predict_match(cargado, "AAA", "BBB")
    assert np.array_equal(pred_a.matrix, pred_b.matrix)
    assert pred_a.lambda_home == pred_b.lambda_home
    assert pred_a.lambda_away == pred_b.lambda_away
    assert (pred_a.prob_home, pred_a.prob_draw, pred_a.prob_away) == (
        pred_b.prob_home,
        pred_b.prob_draw,
        pred_b.prob_away,
    )
    assert pred_a.top_scores == pred_b.top_scores


# ---------------------------------------------------------------------------
# R12 — error con parámetros sin entrenar
# ---------------------------------------------------------------------------


def test_params_inexistentes_not_fitted_error(tmp_path: Path) -> None:
    """R12: archivo inexistente → NotFittedError con la ruta."""
    with pytest.raises(NotFittedError, match="no_entrenado.json"):
        load_params(tmp_path / "no_entrenado.json")


def test_json_invalido_not_fitted_error(tmp_path: Path) -> None:
    """R12: JSON sin las claves del contrato → NotFittedError con el motivo."""
    incompleto = tmp_path / "incompleto.json"
    incompleto.write_text(json.dumps({"mu": 0.1, "rho": 0.0}), encoding="utf-8")
    with pytest.raises(NotFittedError, match="attack"):
        load_params(incompleto)
    corrupto = tmp_path / "corrupto.json"
    corrupto.write_text("{esto no es json", encoding="utf-8")
    with pytest.raises(NotFittedError, match="corrupto.json"):
        load_params(corrupto)


# ---------------------------------------------------------------------------
# R13 — localía en predicción SOLO para anfitrionas
# ---------------------------------------------------------------------------


def test_h_uno_solo_anfitriona() -> None:
    """R13: h=1 SOLO si el local es anfitriona (MEX/USA/CAN); gamma nunca en away."""
    params = manual_params()
    mu, gamma = params.mu, params.home_advantage
    att, deff = params.attack, params.defense

    # anfitrionas como local → h = 1 (gamma entra en lambda_home)
    for host in ("MEX", "USA", "CAN"):
        pred = predict_match(params, host, "ARG")
        esperado_lh = math.exp(mu + att[host] - deff["ARG"] + gamma)
        esperado_la = math.exp(mu + att["ARG"] - deff[host])
        assert pred.lambda_home == pytest.approx(esperado_lh, abs=1e-12)
        assert pred.lambda_away == pytest.approx(esperado_la, abs=1e-12)

    # local NO anfitriona → h = 0 (sede neutral, sin gamma)
    pred = predict_match(params, "ARG", "BRA")
    assert pred.lambda_home == pytest.approx(math.exp(mu + att["ARG"] - deff["BRA"]), abs=1e-12)
    assert pred.lambda_away == pytest.approx(math.exp(mu + att["BRA"] - deff["ARG"]), abs=1e-12)

    # gamma NUNCA afecta a lambda_away, ni siquiera con local anfitriona
    params_gamma_alto = replace(params, home_advantage=0.9)
    base = predict_match(params, "MEX", "ARG")
    alto = predict_match(params_gamma_alto, "MEX", "ARG")
    assert alto.lambda_away == base.lambda_away
    assert alto.lambda_home > base.lambda_home


# ---------------------------------------------------------------------------
# R14 — matriz conjunta de marcadores
# ---------------------------------------------------------------------------


def test_matriz_conjunta_suma_uno() -> None:
    """R14: matriz (max_goals+1)² con tau aplicada y renormalizada; suma 1 (1e−9)."""
    pred = predict_match(manual_params(), "MEX", "ARG")
    assert isinstance(pred.matrix, np.ndarray)  # expuesta para la feature 4
    assert pred.matrix.shape == (11, 11)
    assert pred.matrix.sum() == pytest.approx(1.0, abs=1e-9)
    assert (pred.matrix >= 0.0).all()


def test_max_goals_configurable() -> None:
    """R14: max_goals configurable cambia el soporte y conserva la suma 1."""
    params = manual_params()
    pred15 = predict_match(params, "ARG", "BRA", max_goals=15)
    assert pred15.matrix.shape == (16, 16)
    assert pred15.matrix.sum() == pytest.approx(1.0, abs=1e-9)
    matriz4 = score_matrix(1.5, 1.2, -0.08, max_goals=4)
    assert matriz4.shape == (5, 5)
    assert matriz4.sum() == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# R15 — tau modifica solo marcadores bajos
# ---------------------------------------------------------------------------


def test_tau_solo_modifica_marcadores_bajos() -> None:
    """R15: con rho≠0 pre-normalización solo cambian (0,0),(0,1),(1,0),(1,1)."""
    lh, la, rho, mg = 1.7, 1.1, -0.12, 10
    con_rho = score_matrix(lh, la, rho, mg)
    sin_rho = score_matrix(lh, la, 0.0, mg)

    bajas = np.zeros((mg + 1, mg + 1), dtype=bool)
    bajas[[0, 0, 1, 1], [0, 1, 0, 1]] = True
    # fuera de las 4 celdas bajas, ambas matrices difieren SOLO en el factor
    # de renormalización (ratio constante) ⇒ pre-normalización eran idénticas
    ratio = con_rho[~bajas] / sin_rho[~bajas]
    factor = ratio[0]
    assert np.allclose(ratio, factor, rtol=1e-9, atol=0.0)
    # en las celdas bajas el cambio adicional es exactamente tau (R5)
    esperados = {
        (0, 0): 1 - lh * la * rho,
        (0, 1): 1 + lh * rho,
        (1, 0): 1 + la * rho,
        (1, 1): 1 - rho,
    }
    for (gx, gy), tau in esperados.items():
        assert con_rho[gx, gy] / sin_rho[gx, gy] == pytest.approx(factor * tau, rel=1e-9)
        assert abs(con_rho[gx, gy] / sin_rho[gx, gy] - factor) > 1e-6  # sí cambian
    # la matriz final renormalizada sigue sumando 1 (1e−9)
    assert con_rho.sum() == pytest.approx(1.0, abs=1e-9)
    assert sin_rho.sum() == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# R16 — probabilidades 1X2 y lambdas esperadas
# ---------------------------------------------------------------------------


def test_1x2_suma_uno_y_lambdas_expuestas() -> None:
    """R16: 1X2 derivadas de la matriz (x>y, x=y, x<y), suman 1; lambdas en la salida."""
    params = manual_params()
    pred = predict_match(params, "MEX", "ARG")
    assert pred.prob_home + pred.prob_draw + pred.prob_away == pytest.approx(1.0, abs=1e-9)
    # derivadas exactamente de la matriz conjunta
    assert pred.prob_home == pytest.approx(float(np.tril(pred.matrix, -1).sum()), abs=1e-15)
    assert pred.prob_draw == pytest.approx(float(np.trace(pred.matrix)), abs=1e-15)
    assert pred.prob_away == pytest.approx(float(np.triu(pred.matrix, 1).sum()), abs=1e-15)
    # tasas esperadas del partido expuestas (R4/R13 con h=1 para MEX)
    esperado_lh = math.exp(params.mu + params.attack["MEX"] - params.defense["ARG"] + params.home_advantage)
    esperado_la = math.exp(params.mu + params.attack["ARG"] - params.defense["MEX"])
    assert pred.lambda_home == pytest.approx(esperado_lh, abs=1e-12)
    assert pred.lambda_away == pytest.approx(esperado_la, abs=1e-12)


# ---------------------------------------------------------------------------
# R17 — top-k marcadores más probables
# ---------------------------------------------------------------------------


def test_top_k_descendente_desempate_determinista() -> None:
    """R17: top-k descendente, desempate por (home_goals, away_goals) ascendente."""
    # lambdas idénticas (matriz simétrica) → empates exactos (0,1)/(1,0) y (1,2)/(2,1)
    params = manual_params(mu=math.log(1.3), gamma=0.3, rho=0.0)
    simetricos = replace(
        params,
        attack={"ARG": 0.0, "BRA": 0.0},
        defense={"ARG": 0.0, "BRA": 0.0},
    )
    pred = predict_match(simetricos, "ARG", "BRA", top_k=5)  # h=0: no anfitriona
    assert pred.lambda_home == pred.lambda_away
    probs = [p for _, _, p in pred.top_scores]
    assert probs == sorted(probs, reverse=True)  # orden descendente
    assert [(gx, gy) for gx, gy, _ in pred.top_scores] == [
        (1, 1),
        (0, 1),  # empate con (1,0) → gana el menor (home_goals, away_goals)
        (1, 0),
        (1, 2),  # empate con (2,1) → ídem
        (2, 1),
    ]
    # k configurable
    assert len(predict_match(simetricos, "ARG", "BRA", top_k=3).top_scores) == 3
    assert len(predict_match(simetricos, "ARG", "BRA", top_k=7).top_scores) == 7


# ---------------------------------------------------------------------------
# R18 — equipo desconocido en predicción
# ---------------------------------------------------------------------------


def test_equipo_desconocido_error() -> None:
    """R18: código ausente de attack/defense → UnknownTeamError con el código."""
    params = manual_params()
    with pytest.raises(UnknownTeamError, match="XXX"):
        predict_match(params, "XXX", "ARG")
    with pytest.raises(UnknownTeamError, match="QQQ"):
        predict_match(params, "ARG", "QQQ")
