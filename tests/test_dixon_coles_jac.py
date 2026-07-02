"""Tests del gradiente analítico Dixon-Coles (R12) — feature 5 backtesting.

Tres tests nuevos sobre ``_grad_nll_weighted`` y el flag ``use_analytic_jac``
de ``fit_dixon_coles``. Los tests de la feature 3 (``test_dixon_coles_fit.py`` y
``test_dixon_coles_predict.py``) NO se modifican.

100 % offline, deterministas y sin red. Silver sintético escrito en ``tmp_path``
con el mismo helper del módulo de la feature 3.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import check_grad

from src.models.dixon_coles import (
    DCConfig,
    _grad_nll_weighted,
    fit_dixon_coles,
    nll_weighted,
)

# ---------------------------------------------------------------------------
# Helpers de fixtures compartidos con test_dixon_coles_fit.py (importados para
# reutilizar el generador canónico sin duplicar código).
# ---------------------------------------------------------------------------

from tests.test_dixon_coles_fit import (  # noqa: E402
    synthetic_model_rows,
    write_contract_silver,
)

# Fecha de corte genérica para los tests de este módulo.
_AS_OF = "2026-06-01"


@pytest.fixture(scope="module")
def synthetic_silver(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Silver sintético de 16 equipos × 8 rondas (~1920 partidos) para los tres tests.

    Mismo seed y generador que ``test_recuperacion_parametros_datos_sinteticos``
    de la feature 3 → los tests son comparables.
    """
    tmp = tmp_path_factory.mktemp("dc_jac")
    _, _, _, rows = synthetic_model_rows(n_teams=16, rounds=8, seed=20260609)
    return write_contract_silver(tmp, rows)


# ---------------------------------------------------------------------------
# (a) test_gradiente_vs_numerico — R12
# ---------------------------------------------------------------------------


def test_gradiente_vs_numerico(synthetic_silver: Path) -> None:
    """R12 (a): gradiente analítico ≈ diferencias centrales en varios puntos θ.

    Usa ``scipy.optimize.check_grad`` que computa la norma euclidiana de la
    diferencia entre ``_grad_nll_weighted`` y la aproximación por diferencias
    finitas de orden 1 con paso 1e-7. Se prueba en cuatro puntos distintos,
    incluyendo valores no triviales de ρ.

    Tolerancia: error relativo ≤ 1e-5 (documentado en design.md).
    El error absoluto se normaliza por la norma del gradiente numérico para
    que la tolerancia sea invariante a la escala del problema.
    """
    from src.models.dixon_coles import load_training_data

    config = DCConfig(xi=0.0, reg_lambda=1.0)
    td = load_training_data(_AS_OF, silver_path=synthetic_silver, config=config)
    n_teams = len(td.teams)
    args = (td.x, td.y, td.w, td.h, td.hi, td.ai, n_teams, config.reg_lambda)

    rng = np.random.default_rng(20260609)
    n_params = 3 + 2 * (n_teams - 1)

    # Puntos de prueba: incluyendo rho no trivial positivo y negativo
    thetas = []
    # Punto 1: cero (punto de partida habitual)
    t1 = np.zeros(n_params)
    t1[0] = 0.3
    t1[1] = 0.2
    thetas.append(t1)
    # Punto 2: rho positivo significativo
    t2 = rng.normal(0.0, 0.1, n_params)
    t2[2] = 0.4
    thetas.append(t2)
    # Punto 3: rho negativo significativo
    t3 = rng.normal(0.0, 0.1, n_params)
    t3[2] = -0.35
    thetas.append(t3)
    # Punto 4: valores más grandes (lejos del óptimo)
    t4 = rng.normal(0.0, 0.3, n_params)
    t4[2] = np.clip(t4[2], -0.9, 0.9)
    thetas.append(t4)

    for i, theta in enumerate(thetas):
        err_abs = check_grad(nll_weighted, _grad_nll_weighted, theta, *args)
        # Norma del gradiente numérico para calcular error relativo
        grad_num = np.zeros_like(theta)
        eps = 1e-7
        for k in range(len(theta)):
            tp = theta.copy(); tp[k] += eps
            tm = theta.copy(); tm[k] -= eps
            grad_num[k] = (nll_weighted(tp, *args) - nll_weighted(tm, *args)) / (2 * eps)
        norm_num = float(np.linalg.norm(grad_num))
        rel_err = err_abs / max(norm_num, 1e-10)
        assert rel_err <= 1e-5, (
            f"Punto θ[{i}]: error relativo del gradiente = {rel_err:.2e} > 1e-5 "
            f"(error absoluto={err_abs:.2e}, |grad_num|={norm_num:.2e})"
        )


# ---------------------------------------------------------------------------
# (b) test_optimo_equivalente_jac_on_off — R12
# ---------------------------------------------------------------------------


def test_optimo_equivalente_jac_on_off(synthetic_silver: Path) -> None:
    """R12 (b): el óptimo con jac analítico coincide con el numérico en el fixture.

    Verifica que la NLL final difiere en ≤ 1e-6 relativo y que los parámetros
    principales (mu, gamma, rho) difieren en ≤ 1e-4.
    """
    config = DCConfig(xi=0.0, reg_lambda=1.0, max_iter=1000)
    params_on = fit_dixon_coles(
        _AS_OF, silver_path=synthetic_silver, config=config, use_analytic_jac=True
    )
    params_off = fit_dixon_coles(
        _AS_OF, silver_path=synthetic_silver, config=config, use_analytic_jac=False
    )

    nll_on = params_on.convergencia["neg_log_lik"]
    nll_off = params_off.convergencia["neg_log_lik"]
    rel_nll = abs(nll_on - nll_off) / max(abs(nll_off), 1e-10)
    assert rel_nll <= 1e-6, (
        f"NLL final: jac_on={nll_on:.8f}, jac_off={nll_off:.8f}, "
        f"diferencia relativa={rel_nll:.2e} > 1e-6"
    )

    assert abs(params_on.mu - params_off.mu) <= 1e-4, (
        f"mu: on={params_on.mu:.6f}, off={params_off.mu:.6f}"
    )
    assert abs(params_on.home_advantage - params_off.home_advantage) <= 1e-4, (
        f"gamma: on={params_on.home_advantage:.6f}, off={params_off.home_advantage:.6f}"
    )
    assert abs(params_on.rho - params_off.rho) <= 1e-4, (
        f"rho: on={params_on.rho:.6f}, off={params_off.rho:.6f}"
    )

    # Contrato público intacto: mismo conjunto de equipos en ambos
    assert params_on.attack.keys() == params_off.attack.keys()


# ---------------------------------------------------------------------------
# (c) test_convergencia_con_jac — R12
# ---------------------------------------------------------------------------


def test_convergencia_con_jac(synthetic_silver: Path) -> None:
    """R12 (c): fit con jac analítico converge exitosamente (success=True)."""
    config = DCConfig(xi=0.0, reg_lambda=1.0, max_iter=1000)
    params = fit_dixon_coles(
        _AS_OF, silver_path=synthetic_silver, config=config, use_analytic_jac=True
    )
    assert params.convergencia["success"] is True, (
        f"L-BFGS-B con jac analítico no convergió: {params.convergencia['message']}"
    )
    assert params.convergencia["n_iter"] >= 1
    assert params.n_teams == 16
