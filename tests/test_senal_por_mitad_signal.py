"""tests/test_senal_por_mitad_signal.py — Feature 32, R4: señal λ_1T/λ_2T.

Trazabilidad:
- test_split_conserva_total       → R4 (el reparto conserva λ_total)
- test_half_strength_shrinkage    → R4 (shrinkage tira del share extremo al prior)
- test_muestra_chica_shrink_fuerte→ R4 (n chico → más cerca del prior)
- test_ajuste_rival               → R4 (ajuste por la defensa del rival por mitad)
- test_team_half_shares           → R4 (shares desde el silver por-mitad)
"""

from __future__ import annotations

import pandas as pd

from src.models.half_signal import (
    half_lambdas,
    shrink_share,
    split_lambda,
    team_half_shares,
)


def test_split_conserva_total():
    """R4: split_lambda reparte sin inventar volumen (λ_1T+λ_2T = λ_total)."""
    l1, l2 = split_lambda(1.6, share_1t=0.4)
    assert abs((l1 + l2) - 1.6) < 1e-9
    assert abs(l1 - 0.64) < 1e-9


def test_half_strength_shrinkage():
    """R4: shrink_share tira de un share extremo hacia el prior (k>n → más cerca del prior)."""
    s = shrink_share(raw=0.82, n=5, k=12, prior=0.54)
    assert 0.54 < s < 0.82
    assert abs(s - 0.54) < abs(s - 0.82)


def test_muestra_chica_shrink_fuerte():
    """R4: con n chico el share regresa fuerte al prior; con n grande conserva lo crudo."""
    prior = 0.5
    s_small = shrink_share(raw=0.9, n=2, k=12, prior=prior)
    s_large = shrink_share(raw=0.9, n=60, k=12, prior=prior)
    assert abs(s_small - prior) < abs(s_large - prior)
    assert s_large > s_small


def test_ajuste_rival():
    """R4: A reparte parejo, pero B encaja sobre todo en 2T → λ de A escora al 2T (conserva total)."""
    l1, l2 = half_lambdas(
        lambda_total=2.0,
        att_share={"1T": 0.5, "2T": 0.5},
        opp_def_share={"1T": 0.2, "2T": 0.8},
    )
    assert l2 > l1
    assert abs((l1 + l2) - 2.0) < 1e-9


def test_team_half_shares():
    """R4: team_half_shares deriva att/def share por mitad y n desde el silver."""
    # SUI: marca parejo pero encaja casi todo en 2T
    df = pd.DataFrame(
        [
            {"team_code": "SUI", "half": "1T", "gf": 24, "ga": 7},
            {"team_code": "SUI", "half": "2T", "gf": 25, "ga": 27},
        ]
    )
    sh = team_half_shares(df, "SUI")
    assert abs(sh["att"]["1T"] - 24 / 49) < 1e-9
    assert abs(sh["def"]["2T"] - 27 / 34) < 1e-9  # concede 79% de sus goles en 2T
