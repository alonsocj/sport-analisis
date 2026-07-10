"""tests/test_senal_por_mitad_markets.py — Feature 32, R5: mercados por mitad.

Trazabilidad:
- test_market_ou_1t          → R5 (O/U goles 1T)
- test_market_ou_2t          → R5 (O/U goles 2T)
- test_market_equipo_marca_2t→ R5 ("equipo marca en 2T")
- test_market_gol_tardio     → R5 ("gol en 76-90")
"""

from __future__ import annotations

import math

from src.markets.by_half import (
    prob_late_goal,
    prob_over_half,
    prob_team_scores,
)


def test_market_ou_1t():
    """R5: O/U 0.5 del 1T = P(≥1 gol) = 1 − e^−(λh+λa)."""
    p = prob_over_half(lambda_home=0.5, lambda_away=0.3, line=0.5)
    assert abs(p - (1 - math.exp(-0.8))) < 1e-6


def test_market_ou_2t():
    """R5: O/U 1.5 del 2T = P(≥2 goles) = 1 − e^−λ(1+λ), λ=λh+λa."""
    p = prob_over_half(lambda_home=1.0, lambda_away=0.6, line=1.5)
    lam = 1.6
    expect = 1 - math.exp(-lam) * (1 + lam)
    assert abs(p - expect) < 1e-6


def test_market_equipo_marca_2t():
    """R5: P(equipo marca en 2T) = 1 − e^−λ2_equipo."""
    assert abs(prob_team_scores(1.6) - (1 - math.exp(-1.6))) < 1e-9
    assert prob_team_scores(0.0) == 0.0


def test_market_gol_tardio():
    """R5: P(gol en 76-90) = 1 − e^−λ76, λ76 = (λ2h+λ2a)·share_bucket."""
    p = prob_late_goal(lambda2_home=1.0, lambda2_away=0.6, bucket_share=0.4)
    lam = 1.6 * 0.4
    assert abs(p - (1 - math.exp(-lam))) < 1e-9
