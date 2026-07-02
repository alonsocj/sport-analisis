"""Factor de forma multiplicativo sobre las λ del Dixon-Coles (R3, R4, Feature 16).

Pipeline: silver matches + Elo externo → build_window → team_form → z-score → exp(γ·z).

Fórmula (R4):
    f_team = (gd_w_team − μ) / σ    con μ,σ sobre los 48 equipos a ``as_of``
    factor  = exp(γ · f_team)
    λ'      = λ_DC · factor

Con γ=0 → factor=1.0 exacto → λ' = λ_DC → predicción IDÉNTICA a v1 (tol 1e-9, R4).
Equipo sin ventana → gd_w=0 → f_team=(0−μ)/σ → factor típicamente cercano a 1 (R7).
σ=0 degenerado → f_team=0 para todos → factor=1.0 (R4).
Equipo no en la lista → z=0 → factor=1.0 (R7).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import pandas as pd

from .config import DEFAULT_FORM_CONFIG, FormConfig
from .metrics import team_form
from .window import build_window, build_window_from_bucket, index_matches_by_team

logger = logging.getLogger(__name__)

#: Callable type alias: (home_code, away_code) -> (mult_home, mult_away).
FormFactorFn = Callable[[str, str], tuple[float, float]]

#: Callable type alias for form factory: as_of -> FormFactorFn.
FormFactoryFn = Callable[[str], FormFactorFn]


def _build_elo_dict(elo: pd.DataFrame | None) -> dict[str, float]:
    """Construye un dict team_code → Elo desde el DataFrame del gold externo (R3).

    Args:
        elo: DataFrame with columns team_code, elo. None or empty → empty dict.

    Returns:
        Dict mapping FIFA code to Elo rating.
    """
    if elo is None or elo.empty:
        return {}
    result: dict[str, float] = {}
    for _, row in elo.iterrows():
        code = str(row.get("team_code", ""))
        try:
            rating = float(row["elo"])
            if code:
                result[code] = rating
        except (ValueError, TypeError, KeyError):
            pass
    return result


def make_form_factor_fn(
    matches: pd.DataFrame,
    as_of: str,
    elo: pd.DataFrame | None,
    gamma: float,
    teams: list[str],
    config: FormConfig = DEFAULT_FORM_CONFIG,
    use_xg: bool = False,
) -> FormFactorFn:
    """Construye el callable form_factor(home, away) -> (mult_home, mult_away) (R3, R4).

    Steps:
    1. Build elo dict from the Elo DataFrame (None → empty dict, neutral weights).
    2. Compute gd_w per team using build_window + team_form with date < as_of (R1).
    3. Standardize gd_w to z-scores over the provided teams list (R4).
    4. Return callable: (home, away) -> (exp(γ·z_home), exp(γ·z_away)).

    Non-regression (R4):
    - γ=0 → identity callable returned immediately (exp(0)=1.0, no computation).
    - γ>0 but team not in ``teams`` → z=0.0 → factor=1.0 (v1 behaviour).
    - σ=0 (degenerate, all same gd_w) → f_team=0 for all → factor=1.0.
    - Empty window → gd_w=0.0 → contributes to the mean/std but factor ~ neutral.

    Anti-fuga (R4): build_window uses strict date < as_of; the predicted match
    is excluded from its own window.

    Feature 26 (forma_xg): ``use_xg=False`` (default) → identical to F16 (R3,
    tol 1e-9).  ``use_xg=True`` → ``team_form`` uses xG-diff per match where
    available; gol-diff otherwise.

    Args:
        matches: Silver matches DataFrame (columns: date, home_code, away_code,
            home_goals, away_goals, tournament).
        as_of: Cutoff date (exclusive). Only matches with date < as_of included.
        elo: External Elo DataFrame with columns team_code, elo. None → no Elo.
        gamma: Form weight γ ∈ [0, 1]. γ=0 → identity (no-regression exact, R4).
        teams: List of team codes to compute form for (typically the 48 WC teams).
        config: FormConfig with k_pre, decay, tier_ratio, opp_elo_pivot, opp_scale.
        use_xg: If True, use xG-diff as signal per match where available (F26, R3).
            Default False → F16 exact (tol 1e-9).

    Returns:
        Callable (home_code, away_code) -> (mult_home, mult_away), with
        mult = exp(γ·z) and z the standardized form score.
    """
    if gamma == 0.0:
        # Fast path: no computation needed → exact no-regression (R4)
        def _identity(home: str, away: str) -> tuple[float, float]:
            return 1.0, 1.0

        return _identity

    elo_dict = _build_elo_dict(elo)

    # Feature 18 (forma_perf): build index once for ALL teams in a single
    # DataFrame traversal, then assemble each window from its pre-built bucket.
    # Reduces complexity from O(N·|matches|) to O(|matches| + N·|bucket|) (R1).
    team_index = index_matches_by_team(matches, teams)

    # Compute gd_w for each team in the 48 (anti-fuga: date < as_of, R1)
    gd_w_by_team: dict[str, float] = {}
    for team in teams:
        window = build_window_from_bucket(
            team_index.get(team, []), as_of, k_pre=config.k_pre
        )
        metrics = team_form(
            window,
            elo_dict,
            decay=config.decay,
            tier_ratio=config.tier_ratio,
            opp_elo_pivot=config.opp_elo_pivot,
            opp_scale=config.opp_scale,
            use_xg=use_xg,
        )
        gd_w_by_team[team] = metrics.gd_w

    # Standardize over the provided teams (R4)
    values = np.array([gd_w_by_team[t] for t in teams], dtype=float)
    mu = float(np.mean(values))
    sigma = float(np.std(values))

    z_by_team: dict[str, float] = {}
    for team in teams:
        if sigma < 1e-10:
            z_by_team[team] = 0.0  # degenerate → factor 1.0 para todos (R4)
        else:
            z_by_team[team] = (gd_w_by_team[team] - mu) / sigma

    logger.debug(
        "forma_reciente: μ=%.4f σ=%.4f γ=%.4f as_of=%s %d equipos",
        mu,
        sigma,
        gamma,
        as_of,
        len(teams),
    )

    def _form_factor(home: str, away: str) -> tuple[float, float]:
        # Unknown team → z=0.0 → factor=1.0 → v1 behaviour (R7)
        z_home = z_by_team.get(home, 0.0)
        z_away = z_by_team.get(away, 0.0)
        return float(np.exp(gamma * z_home)), float(np.exp(gamma * z_away))

    return _form_factor


def make_form_factory(
    matches: pd.DataFrame,
    elo: pd.DataFrame | None,
    gamma: float,
    teams: list[str],
    config: FormConfig = DEFAULT_FORM_CONFIG,
    use_xg: bool = False,
) -> FormFactoryFn:
    """Construye un form_factory(as_of) -> form_factor_fn para uso en backtest walk-forward (R5).

    The factory pre-captures matches, elo, gamma, teams, config and use_xg; at each
    call with a new as_of it rebuilds the form_factor callable using that date as the
    anti-fuga cutoff. Used in backtest/walkforward.run() to compute form per window.

    Feature 26 (forma_xg): ``use_xg`` is forwarded to each ``make_form_factor_fn``
    call.  Default False → F16 exact (R3).

    Args:
        matches: Silver matches DataFrame (loaded once outside the walk-forward loop).
        elo: External Elo DataFrame. None → neutral weights for all opponents.
        gamma: Form weight γ. γ=0 → identity factory (no computation per step).
        teams: List of team codes (typically the 48 WC teams).
        config: FormConfig with all parameters.
        use_xg: If True, use xG-diff as form signal where available (F26, R3).
            Default False → F16 exact (tol 1e-9).

    Returns:
        Callable (as_of: str) -> FormFactorFn.
    """
    if gamma == 0.0:
        def _identity_factory(as_of: str) -> FormFactorFn:
            def _identity(home: str, away: str) -> tuple[float, float]:
                return 1.0, 1.0

            return _identity

        return _identity_factory

    def _factory(as_of: str) -> FormFactorFn:
        return make_form_factor_fn(matches, as_of, elo, gamma, teams, config, use_xg=use_xg)

    return _factory
