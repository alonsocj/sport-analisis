"""Tests de ajuste del modelo Dixon-Coles (R1–R10) — feature 3 modelo_resultado.

100 % offline y deterministas: silver sintético escrito en ``tmp_path`` con el
esquema del contrato de la feature 2, semillas fijas (``np.random.default_rng``),
cero red, cero ``now()`` implícito, cero ``API_FOOTBALL_KEY``.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.models.dixon_coles import (
    DCConfig,
    SilverNotFoundError,
    decay_weights,
    fit_dixon_coles,
    load_training_data,
    match_rates,
    nll_weighted,
    score_matrix,
    tau_low_scores,
)

AS_OF = "2025-06-01"

# Esquema/orden EXACTOS del contrato silver de la feature 2 (specs/feature_store).
SILVER_COLUMNS: tuple[str, ...] = (
    "match_id",
    "date",
    "home_code",
    "away_code",
    "home_team",
    "away_team",
    "home_goals",
    "away_goals",
    "tournament",
    "neutral",
    "source",
    "home_corners",
    "away_corners",
    "home_cards",
    "away_cards",
    "home_shots",
    "away_shots",
    "home_shots_on_target",
    "away_shots_on_target",
    "home_possession",
    "away_possession",
)

_STAT_COLUMNS = SILVER_COLUMNS[11:]


def write_contract_silver(dir_path: Path, matches: list[dict[str, Any]]) -> Path:
    """Escribe un silver sintético con el esquema completo del contrato (helper compartido).

    ``matches``: dicts con ``date, home_code, away_code, home_goals, away_goals,
    neutral``. El resto de columnas del contrato se rellena de forma determinista
    (stats nulas, como las filas ``public_csv`` reales).
    """
    rows = []
    for i, m in enumerate(matches):
        row: dict[str, Any] = {
            "match_id": f"m{i:06d}",
            "date": m["date"],
            "home_code": m["home_code"],
            "away_code": m["away_code"],
            "home_team": m["home_code"],
            "away_team": m["away_code"],
            "home_goals": int(m["home_goals"]),
            "away_goals": int(m["away_goals"]),
            "tournament": "Friendly",
            "neutral": bool(m["neutral"]),
            "source": "public_csv",
        }
        row.update({c: None for c in _STAT_COLUMNS})
        rows.append(row)
    df = pd.DataFrame(rows, columns=list(SILVER_COLUMNS))
    path = dir_path / "matches.csv"
    df.to_csv(path, index=False)
    return path


def make_round_robin_rows(
    teams: tuple[str, ...],
    rounds: int,
    seed: int,
    start: str = "2025-01-01",
    neutral: bool = False,
) -> list[dict[str, Any]]:
    """Calendario round-robin ida/vuelta con marcadores Poisson de semilla fija."""
    rng = np.random.default_rng(seed)
    base = date.fromisoformat(start)
    rows: list[dict[str, Any]] = []
    k = 0
    for _ in range(rounds):
        for i, home in enumerate(teams):
            for j, away in enumerate(teams):
                if i == j:
                    continue
                rows.append(
                    {
                        "date": (base + timedelta(days=k % 120)).isoformat(),
                        "home_code": home,
                        "away_code": away,
                        "home_goals": int(rng.poisson(1.4)),
                        "away_goals": int(rng.poisson(1.1)),
                        "neutral": neutral,
                    }
                )
                k += 1
    return rows


# Parámetros verdaderos del generador sintético del propio modelo (R9, design.md).
TRUE_MU = 0.1
TRUE_GAMMA = 0.25
TRUE_RHO = -0.1


def synthetic_model_rows(
    n_teams: int = 16, rounds: int = 8, seed: int = 20260609
) -> tuple[tuple[str, ...], np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """Partidos muestreados de la matriz conjunta del PROPIO modelo (R9).

    ``att/def ~ Normal(0, 0.35)`` centrados a suma cero con semilla fija; el
    marcador de cada partido se muestrea de ``score_matrix`` (``rng.choice``
    sobre la matriz aplanada). Calendario round-robin ida/vuelta repetido
    (``n_teams·(n_teams−1)·rounds`` partidos), fechas dentro de la ventana.
    """
    teams = tuple(f"T{i:02d}" for i in range(n_teams))
    rng = np.random.default_rng(seed)
    att = rng.normal(0.0, 0.35, n_teams)
    att -= att.mean()
    deff = rng.normal(0.0, 0.35, n_teams)
    deff -= deff.mean()
    base = date(2024, 1, 1)
    max_goals = 10
    side = max_goals + 1
    rows: list[dict[str, Any]] = []
    k = 0
    for i in range(n_teams):
        for j in range(n_teams):
            if i == j:
                continue
            lh, la = match_rates(
                TRUE_MU, TRUE_GAMMA, att[i], deff[i], att[j], deff[j], 1.0
            )
            matrix = score_matrix(float(lh), float(la), TRUE_RHO, max_goals)
            draws = rng.choice(side * side, size=rounds, p=matrix.ravel())
            for r, idx in enumerate(draws):
                rows.append(
                    {
                        "date": (base + timedelta(days=(k + r * 240) % 730)).isoformat(),
                        "home_code": teams[i],
                        "away_code": teams[j],
                        "home_goals": int(idx) // side,
                        "away_goals": int(idx) % side,
                        "neutral": False,  # h = 1 en todos (R4)
                    }
                )
            k += 1
    return teams, att, deff, rows


@pytest.fixture(scope="module")
def small_fit(tmp_path_factory: pytest.TempPathFactory):
    """Silver pequeño (4 equipos, 24 partidos) + ajuste con la config por defecto."""
    tmp = tmp_path_factory.mktemp("dc_fit")
    silver = write_contract_silver(
        tmp, make_round_robin_rows(("AAA", "BBB", "CCC", "DDD"), rounds=2, seed=11)
    )
    params = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig())
    return silver, params


# ---------------------------------------------------------------------------
# R1 — carga del silver y validación de contrato
# ---------------------------------------------------------------------------


def test_carga_silver_contrato(small_fit) -> None:
    """R1: lee el silver con las columnas del contrato (las extra se ignoran)."""
    _, params = small_fit
    assert params.n_matches == 24
    assert set(params.attack) == {"AAA", "BBB", "CCC", "DDD"}
    assert set(params.defense) == {"AAA", "BBB", "CCC", "DDD"}
    assert params.n_teams == 4
    assert isinstance(params.mu, float)
    assert params.low_data_teams == []  # 12 partidos por equipo >= min_matches


def test_silver_inexistente_o_sin_columnas_error(tmp_path: Path) -> None:
    """R1: archivo inexistente o columna ausente → SilverNotFoundError claro, sin salida."""
    missing_path = tmp_path / "no_existe" / "matches.csv"
    with pytest.raises(SilverNotFoundError, match="matches.csv"):
        fit_dixon_coles(AS_OF, silver_path=missing_path)

    silver = write_contract_silver(
        tmp_path, make_round_robin_rows(("AAA", "BBB"), rounds=1, seed=3)
    )
    df = pd.read_csv(silver)
    df.drop(columns=["neutral"]).to_csv(silver, index=False)
    with pytest.raises(SilverNotFoundError, match="neutral"):
        fit_dixon_coles(AS_OF, silver_path=silver)


# ---------------------------------------------------------------------------
# R2 — recorte temporal con as_of_date inyectada
# ---------------------------------------------------------------------------


def test_recorte_temporal_estricto(tmp_path: Path) -> None:
    """R2: solo `from_date <= date < as_of_date`; el límite superior queda FUERA."""
    silver = write_contract_silver(
        tmp_path,
        [
            {"date": "2023-12-31", "home_code": "OLD", "away_code": "AAA", "home_goals": 1, "away_goals": 0, "neutral": False},
            {"date": "2024-01-01", "home_code": "AAA", "away_code": "BBB", "home_goals": 2, "away_goals": 1, "neutral": False},
            {"date": "2024-05-31", "home_code": "CCC", "away_code": "DDD", "home_goals": 0, "away_goals": 0, "neutral": True},
            {"date": "2024-06-01", "home_code": "CUT", "away_code": "AAA", "home_goals": 3, "away_goals": 3, "neutral": False},
            {"date": "2024-08-01", "home_code": "FUT", "away_code": "BBB", "home_goals": 1, "away_goals": 1, "neutral": False},
        ],
    )
    config = DCConfig(from_date="2024-01-01")
    td = load_training_data("2024-06-01", silver_path=silver, config=config)
    assert td.x.size == 2  # solo 2024-01-01 (== from_date, dentro) y 2024-05-31
    assert set(td.teams) == {"AAA", "BBB", "CCC", "DDD"}
    for fuera in ("OLD", "CUT", "FUT"):  # anti-leakage: date >= as_of_date fuera
        assert fuera not in td.teams


def test_fecha_invalida_error(tmp_path: Path) -> None:
    """R2: as_of_date/from_date sin formato YYYY-MM-DD → ValueError claro."""
    silver = write_contract_silver(
        tmp_path, make_round_robin_rows(("AAA", "BBB"), rounds=1, seed=3)
    )
    with pytest.raises(ValueError, match="as_of_date"):
        fit_dixon_coles("2026/06/01", silver_path=silver)
    with pytest.raises(ValueError, match="as_of_date"):
        fit_dixon_coles("2026-6-1", silver_path=silver)
    with pytest.raises(ValueError, match="from_date"):
        fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig(from_date="01-01-2018"))


def test_recorte_vacio_error(tmp_path: Path) -> None:
    """R2: recorte sin partidos → error claro con la ventana (no hay nada que ajustar)."""
    silver = write_contract_silver(
        tmp_path, make_round_robin_rows(("AAA", "BBB"), rounds=1, seed=3, start="2025-01-01")
    )
    with pytest.raises(ValueError, match="0 partidos"):
        fit_dixon_coles("2020-01-01", silver_path=silver)


# ---------------------------------------------------------------------------
# R3 — pesos de decaimiento temporal
# ---------------------------------------------------------------------------


def test_pesos_decrecientes_con_antiguedad() -> None:
    """R3: w = exp(−xi·días/365.25), estrictamente decreciente con la antigüedad."""
    fechas = ["2026-05-31", "2026-03-01", "2025-06-01", "2022-06-01"]
    w = decay_weights(fechas, "2026-06-01", xi=0.65)
    assert w.shape == (4,)
    assert np.all(np.diff(w) < 0)  # a más días desde as_of_date, menor peso
    assert w[0] == pytest.approx(math.exp(-0.65 * 1 / 365.25), abs=1e-15)
    assert w[2] == pytest.approx(math.exp(-0.65 * 365 / 365.25), abs=1e-15)


def test_xi_cero_pesos_unitarios() -> None:
    """R3: con xi = 0 todos los pesos valen exactamente 1."""
    w = decay_weights(["2018-01-01", "2024-03-15", "2026-05-31"], "2026-06-01", xi=0.0)
    assert (w == 1.0).all()


# ---------------------------------------------------------------------------
# R4 — especificación de tasas y localía en entrenamiento
# ---------------------------------------------------------------------------


def test_match_rates_especificacion() -> None:
    """R4: lambdas exactas de la especificación; gamma SOLO en lambda_home vía h."""
    mu, gamma = 0.12, 0.3
    att_h, def_h, att_a, def_a = 0.4, 0.2, -0.1, 0.05
    lh, la = match_rates(mu, gamma, att_h, def_h, att_a, def_a, h=1.0)
    assert float(lh) == pytest.approx(math.exp(0.12 + 0.4 - 0.05 + 0.3), abs=1e-12)
    assert float(la) == pytest.approx(math.exp(0.12 - 0.1 - 0.2), abs=1e-12)

    lh0, la0 = match_rates(mu, gamma, att_h, def_h, att_a, def_a, h=0.0)
    assert float(lh0) == pytest.approx(math.exp(0.12 + 0.4 - 0.05), abs=1e-12)
    # gamma NUNCA interviene en lambda_away, ni con h = 1
    lh_g, la_g = match_rates(mu, 0.9, att_h, def_h, att_a, def_a, h=1.0)
    assert float(la_g) == float(la) == float(la0)
    assert float(lh_g) > float(lh)


def test_gamma_solo_si_no_neutral_entrenamiento(tmp_path: Path) -> None:
    """R4: en entrenamiento h = 1−neutral; con todo neutral, gamma no afecta la NLL."""
    mixto = [
        {"date": "2025-01-01", "home_code": "AAA", "away_code": "BBB", "home_goals": 2, "away_goals": 0, "neutral": False},
        {"date": "2025-01-02", "home_code": "CCC", "away_code": "DDD", "home_goals": 1, "away_goals": 1, "neutral": True},
        {"date": "2025-01-03", "home_code": "BBB", "away_code": "CCC", "home_goals": 0, "away_goals": 1, "neutral": False},
        {"date": "2025-01-04", "home_code": "DDD", "away_code": "AAA", "home_goals": 3, "away_goals": 2, "neutral": True},
    ]
    td = load_training_data(AS_OF, write_contract_silver(tmp_path, mixto))
    assert np.array_equal(td.h, np.array([1.0, 0.0, 1.0, 0.0]))  # h = 1 − neutral

    n = len(td.teams)
    theta_g0 = np.zeros(3 + 2 * (n - 1))
    theta_g0[0] = 0.1
    theta_g5 = theta_g0.copy()
    theta_g5[1] = 0.5
    args = (td.x, td.y, td.w, td.h, td.hi, td.ai, n, 0.0)
    assert nll_weighted(theta_g0, *args) != nll_weighted(theta_g5, *args)

    # mismo dataset pero TODO neutral → h = 0 y gamma es irrelevante en la NLL
    neutro = [dict(m, neutral=True) for m in mixto]
    dir_neutro = tmp_path / "neutro"
    dir_neutro.mkdir()
    td_n = load_training_data(AS_OF, write_contract_silver(dir_neutro, neutro))
    assert np.array_equal(td_n.h, np.zeros(4))
    args_n = (td_n.x, td_n.y, td_n.w, td_n.h, td_n.hi, td_n.ai, n, 0.0)
    assert nll_weighted(theta_g0, *args_n) == nll_weighted(theta_g5, *args_n)


# ---------------------------------------------------------------------------
# R5 — corrección tau en marcadores bajos
# ---------------------------------------------------------------------------


def test_tau_definicion_celdas_bajas() -> None:
    """R5: tau EXACTA en (0,0), (0,1), (1,0), (1,1) y 1 en cualquier otro marcador."""
    lh, la, rho = 1.7, 1.1, -0.12
    assert float(tau_low_scores(0, 0, lh, la, rho)) == pytest.approx(1 - lh * la * rho, abs=1e-15)
    assert float(tau_low_scores(0, 1, lh, la, rho)) == pytest.approx(1 + lh * rho, abs=1e-15)
    assert float(tau_low_scores(1, 0, lh, la, rho)) == pytest.approx(1 + la * rho, abs=1e-15)
    assert float(tau_low_scores(1, 1, lh, la, rho)) == pytest.approx(1 - rho, abs=1e-15)
    for x, y in ((0, 2), (2, 0), (1, 2), (2, 2), (5, 3)):
        assert float(tau_low_scores(x, y, lh, la, rho)) == 1.0
    # forma vectorizada con lambdas por partido
    x = np.array([0, 0, 1, 1, 3])
    y = np.array([0, 1, 0, 1, 2])
    lhs = np.array([1.0, 1.5, 2.0, 0.8, 1.2])
    las = np.array([0.9, 1.1, 1.3, 1.0, 1.4])
    esperado = np.array(
        [1 - 1.0 * 0.9 * rho, 1 + 1.5 * rho, 1 + 1.3 * rho, 1 - rho, 1.0]
    )
    assert np.allclose(tau_low_scores(x, y, lhs, las, rho), esperado, atol=1e-15)


# ---------------------------------------------------------------------------
# R6 — NLL vectorizada, convergencia y no-convergencia
# ---------------------------------------------------------------------------


def _nll_referencia_bucle(
    theta: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    h: np.ndarray,
    hi: np.ndarray,
    ai: np.ndarray,
    n_teams: int,
    reg_lambda: float,
) -> float:
    """Referencia partido a partido (bucle Python puro) con la MISMA fórmula (R6)."""
    mu, gamma, rho = float(theta[0]), float(theta[1]), float(theta[2])
    att = [float(v) for v in theta[3 : 3 + n_teams - 1]]
    att.append(-float(np.sum(theta[3 : 3 + n_teams - 1])))
    deff = [float(v) for v in theta[3 + n_teams - 1 :]]
    deff.append(-float(np.sum(theta[3 + n_teams - 1 :])))
    total = 0.0
    for i in range(len(x)):
        lh = math.exp(mu + att[hi[i]] - deff[ai[i]] + gamma * h[i])
        la = math.exp(mu + att[ai[i]] - deff[hi[i]])
        if x[i] == 0 and y[i] == 0:
            tau = 1 - lh * la * rho
        elif x[i] == 0 and y[i] == 1:
            tau = 1 + lh * rho
        elif x[i] == 1 and y[i] == 0:
            tau = 1 + la * rho
        elif x[i] == 1 and y[i] == 1:
            tau = 1 - rho
        else:
            tau = 1.0
        tau = max(tau, 1e-10)
        total += w[i] * (
            x[i] * math.log(lh) - lh + y[i] * math.log(la) - la + math.log(tau)
        )
    penalty = reg_lambda * (sum(a * a for a in att) + sum(d * d for d in deff))
    return -total + penalty


def test_nll_coincide_con_referencia_bucle() -> None:
    """R6: el objetivo vectorizado coincide (1e−9) con la referencia por bucle."""
    rng = np.random.default_rng(123)
    n_teams, n = 8, 300
    hi = rng.integers(0, n_teams, n)
    ai = (hi + rng.integers(1, n_teams, n)) % n_teams  # rival siempre distinto
    x = rng.poisson(1.4, n).astype(float)
    y = rng.poisson(1.1, n).astype(float)
    w = rng.uniform(0.2, 1.0, n)
    h = rng.integers(0, 2, n).astype(float)
    theta = rng.normal(0.0, 0.25, 3 + 2 * (n_teams - 1))
    theta[2] = -0.12  # rho dentro de la cota
    for reg_lambda in (0.0, 1.0):
        vectorizado = nll_weighted(theta, x, y, w, h, hi, ai, n_teams, reg_lambda)
        referencia = _nll_referencia_bucle(theta, x, y, w, h, hi, ai, n_teams, reg_lambda)
        assert vectorizado == pytest.approx(referencia, abs=1e-9)


def test_fit_reporta_convergencia(small_fit) -> None:
    """R6: convergencia registrada con success, iteraciones, mensaje y objetivo."""
    _, params = small_fit
    conv = params.convergencia
    assert conv["success"] is True
    assert isinstance(conv["n_iter"], int) and conv["n_iter"] >= 1
    assert isinstance(conv["message"], str)
    assert isinstance(conv["neg_log_lik"], float) and math.isfinite(conv["neg_log_lik"])


def test_no_convergencia_warning_sin_abortar(small_fit) -> None:
    """R6: optimizador sin converger → warning + success=False, SIN abortar."""
    silver, _ = small_fit
    with pytest.warns(RuntimeWarning, match="no convergió"):
        params = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig(max_iter=1))
    assert params.convergencia["success"] is False
    assert set(params.attack) == {"AAA", "BBB", "CCC", "DDD"}  # parámetros disponibles


def test_maxfun_escala_con_dimension(small_fit, monkeypatch: pytest.MonkeyPatch) -> None:
    """R6: maxfun = max_iter·(n_params+1) en las options de L-BFGS-B.

    Sin ``jac``, el gradiente por diferencias finitas consume ``n_params+1``
    evaluaciones de f por iteración; sin escalar ``maxfun``, el default de scipy
    (15000) agotaría las evaluaciones antes de ``maxiter`` en dimensiones reales.
    Spy sobre ``minimize`` tal y como está importado en ``src.models.dixon_coles``.
    """
    import src.models.dixon_coles as dc

    capturado: dict[str, Any] = {}
    minimize_real = dc.minimize

    def spy_minimize(fun, x0, *args, **kwargs):
        capturado["n_params"] = int(np.asarray(x0).size)
        capturado["options"] = dict(kwargs["options"])
        return minimize_real(fun, x0, *args, **kwargs)

    monkeypatch.setattr(dc, "minimize", spy_minimize)
    silver, _ = small_fit
    config = DCConfig(max_iter=2)  # pequeño → no-convergencia esperada (R6)
    with pytest.warns(RuntimeWarning, match="no convergió"):
        params = fit_dixon_coles(AS_OF, silver_path=silver, config=config)

    assert capturado["n_params"] == 3 + 2 * (4 - 1)  # dim de theta con 4 equipos
    assert capturado["options"]["maxiter"] == config.max_iter
    assert capturado["options"]["maxfun"] == config.max_iter * (capturado["n_params"] + 1)
    assert set(params.attack) == {"AAA", "BBB", "CCC", "DDD"}  # devuelve parámetros


# ---------------------------------------------------------------------------
# R7 — identificabilidad
# ---------------------------------------------------------------------------


def test_identificabilidad_sum_att_def_cero(small_fit) -> None:
    """R7: sum(att) = 0 y sum(def) = 0 (1e−8) por reparametrización."""
    _, params = small_fit
    assert abs(sum(params.attack.values())) <= 1e-8
    assert abs(sum(params.defense.values())) <= 1e-8


# ---------------------------------------------------------------------------
# R8 — universo de equipos y equipos con pocos partidos
# ---------------------------------------------------------------------------


def _silver_con_equipo_escaso(tmp_path: Path) -> Path:
    """4 equipos bien muestreados (12 partidos c/u) + 'AAA' con solo 2 (goleadas)."""
    rows = make_round_robin_rows(("KKK", "LLL", "NNN", "PPP"), rounds=2, seed=29)
    rows.append({"date": "2025-02-01", "home_code": "AAA", "away_code": "KKK", "home_goals": 4, "away_goals": 0, "neutral": False})
    rows.append({"date": "2025-02-15", "home_code": "KKK", "away_code": "AAA", "home_goals": 0, "away_goals": 3, "neutral": False})
    return write_contract_silver(tmp_path, rows)


def test_equipo_pocos_partidos_listado_low_data(tmp_path: Path) -> None:
    """R8: equipo con < min_matches partidos se ajusta igual y se lista en low_data_teams."""
    silver = _silver_con_equipo_escaso(tmp_path)
    params = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig())
    assert params.low_data_teams == ["AAA"]  # 2 partidos < min_matches=5
    assert "AAA" in params.attack and "AAA" in params.defense  # incluido en el ajuste
    assert set(params.attack) == {"AAA", "KKK", "LLL", "NNN", "PPP"}


def test_shrinkage_mayor_reg_menor_magnitud(tmp_path: Path) -> None:
    """R8: a mayor reg_lambda, menor magnitud de att/def del equipo con pocos partidos."""
    silver = _silver_con_equipo_escaso(tmp_path)
    suave = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig(reg_lambda=0.1))
    fuerte = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig(reg_lambda=10.0))
    mag_suave = abs(suave.attack["AAA"]) + abs(suave.defense["AAA"])
    mag_fuerte = abs(fuerte.attack["AAA"]) + abs(fuerte.defense["AAA"])
    assert mag_suave > 0.0
    assert mag_fuerte < mag_suave  # contracción hacia 0


# ---------------------------------------------------------------------------
# R9 — recuperación de parámetros en datos sintéticos del propio modelo
# ---------------------------------------------------------------------------


def test_recuperacion_parametros_datos_sinteticos(tmp_path: Path) -> None:
    """R9: con ~1920 partidos sintéticos (semilla fija, xi=0, reg=0) recupera los
    parámetros verdaderos dentro de las tolerancias holgadas de design.md."""
    teams, att_true, def_true, rows = synthetic_model_rows(n_teams=16, rounds=8, seed=20260609)
    assert len(rows) == 16 * 15 * 8  # >= ~1900 partidos
    silver = write_contract_silver(tmp_path, rows)
    config = DCConfig(xi=0.0, reg_lambda=0.0)  # aísla la MLE
    params = fit_dixon_coles("2026-06-01", silver_path=silver, config=config)

    assert params.convergencia["success"] is True
    assert abs(params.mu - TRUE_MU) <= 0.05
    assert abs(params.home_advantage - TRUE_GAMMA) <= 0.05
    assert abs(params.rho - TRUE_RHO) <= 0.1
    att_hat = np.array([params.attack[t] for t in teams])
    def_hat = np.array([params.defense[t] for t in teams])
    assert np.max(np.abs(att_hat - att_true)) <= 0.15
    assert np.max(np.abs(def_hat - def_true)) <= 0.15


# ---------------------------------------------------------------------------
# R10 — determinismo de reentrenamiento
# ---------------------------------------------------------------------------


def test_reentrenamiento_determinista(small_fit) -> None:
    """R10: misma entrada y configuración → parámetros idénticos (≤ 1e−12)."""
    silver, primero = small_fit
    segundo = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig())
    assert abs(primero.mu - segundo.mu) <= 1e-12
    assert abs(primero.home_advantage - segundo.home_advantage) <= 1e-12
    assert abs(primero.rho - segundo.rho) <= 1e-12
    assert primero.attack.keys() == segundo.attack.keys()
    for code in primero.attack:
        assert abs(primero.attack[code] - segundo.attack[code]) <= 1e-12
        assert abs(primero.defense[code] - segundo.defense[code]) <= 1e-12
    assert primero.n_matches == segundo.n_matches
    assert primero.convergencia == segundo.convergencia
