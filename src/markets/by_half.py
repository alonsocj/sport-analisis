"""src/markets/by_half.py — Feature 32, R5: mercados por mitad (1T/2T).

Aplica el motor Poisson por mitad usando ``λ_1T``/``λ_2T`` por equipo (de
``src.models.half_signal``): over/under de goles por mitad, "equipo marca en 2T"
y "gol en 76-90". Módulo NUEVO: no muta ``goals.py`` ni ``corners.py``.

Aproximación: dentro de una mitad los goles de cada equipo son Poisson
independientes (sin corrección Dixon-Coles de marcadores bajos, que se define para
el partido completo). El motor conjunto reutiliza ``goals.prob_over``.
"""

from __future__ import annotations

import math

import numpy as np

from .goals import prob_over

_MAX_GOALS_HALF = 12  # cola holgada: truncar en 12 deja error < 1e-9 para λ por mitad < 2


def _poisson_pmf(k: int, lam: float) -> float:
    """PMF de Poisson P(X=k) para λ ≥ 0."""
    if lam < 0:
        raise ValueError(f"λ negativo: {lam!r}")
    return math.exp(-lam) * lam**k / math.factorial(k)


def half_score_matrix(
    lambda_home: float, lambda_away: float, max_goals: int = _MAX_GOALS_HALF
) -> np.ndarray:
    """Matriz conjunta de marcadores de una mitad (Poisson independientes) (R5).

    Args:
        lambda_home: Goles esperados del local en la mitad.
        lambda_away: Goles esperados del visitante en la mitad.
        max_goals: Truncado de la cola (por lado).

    Returns:
        Matriz ``M[x][y] = P(home=x, away=y)`` (independencia → producto externo).
    """
    home = np.array([_poisson_pmf(x, lambda_home) for x in range(max_goals + 1)])
    away = np.array([_poisson_pmf(y, lambda_away) for y in range(max_goals + 1)])
    return np.outer(home, away)


def prob_over_half(lambda_home: float, lambda_away: float, line: float) -> float:
    """P(goles de la mitad > line) desde la Poisson conjunta de la mitad (R5).

    Args:
        lambda_home / lambda_away: λ por lado de la mitad.
        line: Línea k + 0.5 (0.5, 1.5, …).

    Returns:
        Probabilidad en [0, 1].
    """
    return prob_over(half_score_matrix(lambda_home, lambda_away), line)


def prob_team_scores(lambda_team_half: float) -> float:
    """P(el equipo marca ≥1 gol en la mitad) = 1 − e^−λ (R5).

    Args:
        lambda_team_half: λ del equipo en la mitad (p.ej. λ_2T del equipo).

    Returns:
        Probabilidad en [0, 1].
    """
    return 1.0 - math.exp(-lambda_team_half)


def prob_late_goal(
    lambda2_home: float, lambda2_away: float, bucket_share: float
) -> float:
    """P(hay gol en el 76-90) = 1 − e^−λ76 (R5).

    ``λ76 = (λ_2T_home + λ_2T_away) · bucket_share``, donde ``bucket_share`` es la
    fracción del 2T que cae en el 76-90 (prior direccional del histórico por-bucket).

    Args:
        lambda2_home / lambda2_away: λ del 2T por lado.
        bucket_share: Fracción del 2T atribuible al 76-90 (0..1).

    Returns:
        Probabilidad en [0, 1].
    """
    lam76 = (lambda2_home + lambda2_away) * bucket_share
    return 1.0 - math.exp(-lam76)
