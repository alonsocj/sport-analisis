"""Métricas de forma ponderadas por recencia y calidad de rival (R2, R3, Feature 16).

Fórmula de peso combinado por partido i (ventana en orden ascendente, i=0 más antiguo):
    rank_i = n - 1 - i         (0 = más reciente, n-1 = más antiguo)
    tier_i = tier_ratio si is_group_wc, else 1.0
    q_i    = clip(1 + (elo_opp - pivot) / scale, 0.5, 2.0)
             o 1.0 si el Elo del rival no está disponible (R7)
    W_i    = decay^rank_i * tier_i * q_i

Métricas ponderadas: metric_w = sum(W_i * metric_i) / sum(W_i).

Feature 26 (forma_xg): ``team_form`` acepta ``use_xg=True`` para usar xG-diff como
señal por partido cuando ``xg_for``/``xg_against`` estén disponibles; si no, fallback a
gol-diff. La señal se almacena en el campo existente ``gd_w`` (no se añade un campo
nuevo a ``FormMetrics``). ``use_xg=False`` (default) → camino de código idéntico a F16
(tol 1e-9, R3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import DEFAULT_FORM_CONFIG
from .window import MatchInWindow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FormMetrics:
    """Métricas de forma ponderadas para un equipo (R2).

    Attributes:
        gf_w: Weighted average goals scored.
        ga_w: Weighted average goals conceded.
        gd_w: Weighted goal difference (primary form component used in factor.py, R4).
        ppg_w: Weighted points per game (3/1/0 scheme).
        streak: Recent results string, most recent first (e.g. 'WDL').
    """

    gf_w: float
    ga_w: float
    gd_w: float
    ppg_w: float
    streak: str


#: Returned for empty windows (R7: degradación sin abortar).
_EMPTY_METRICS: FormMetrics = FormMetrics(gf_w=0.0, ga_w=0.0, gd_w=0.0, ppg_w=0.0, streak="")


def team_form(
    window: list[MatchInWindow],
    elo: dict[str, float],
    *,
    decay: float = DEFAULT_FORM_CONFIG.decay,
    tier_ratio: float = DEFAULT_FORM_CONFIG.tier_ratio,
    opp_elo_pivot: float = DEFAULT_FORM_CONFIG.opp_elo_pivot,
    opp_scale: float = DEFAULT_FORM_CONFIG.opp_scale,
    use_xg: bool = False,
) -> FormMetrics:
    """Calcula métricas de forma ponderadas desde la ventana (R2, R3).

    Empty window returns FormMetrics with all zeros and empty streak (R7).
    Unknown opponent Elo → neutral weight q=1.0, no abort (R3, R7).

    Feature 26 (forma_xg): when ``use_xg=True``, the per-match goal-difference
    signal is replaced by ``xg_for - xg_against`` when both are available;
    otherwise falls back to ``gf - ga`` for that match (R2).  The result is
    stored in the existing ``gd_w`` field of ``FormMetrics``.  With
    ``use_xg=False`` (default) the code path is identical to F16 (R3, tol 1e-9).

    Args:
        window: Matches from build_window, sorted ascending by date (oldest first).
        elo: Dict mapping team_code to Elo rating (from external_elo.csv).
            Missing rival → q=1.0 (neutral weight).
        decay: Exponential recency decay. W_i = decay^rank_i (rank 0 = most recent).
        tier_ratio: Weight multiplier for WC group matches vs pre-WC friendlies.
        opp_elo_pivot: Reference Elo for quality adjustment (default 1500).
        opp_scale: Elo scale for quality clip (default 400).
        use_xg: If True, use xG-diff per match where available, else gol-diff (R2, F26).
            Default False → exact F16 behaviour (R3, tol 1e-9).

    Returns:
        FormMetrics with weighted averages and raw streak (most recent first).
        When use_xg=True, gd_w reflects xG-diff (or gol-diff fallback) per match.
    """
    if not window:
        return _EMPTY_METRICS

    n = len(window)
    total_w = 0.0
    gf_sum = 0.0
    ga_sum = 0.0
    gd_sum = 0.0
    ppg_sum = 0.0

    for i, match in enumerate(window):
        rank = n - 1 - i  # 0 = most recent → decay^0 = 1.0 (máximo peso)
        tier = tier_ratio if match.is_group_wc else 1.0

        opp_elo = elo.get(match.opp_code)
        if opp_elo is not None:
            raw_q = 1.0 + (opp_elo - opp_elo_pivot) / opp_scale
            q = max(0.5, min(2.0, raw_q))
        else:
            q = 1.0  # rival sin Elo → peso neutro (R3, R7)
            logger.debug("Elo del rival %s no encontrado; peso neutro q=1.0.", match.opp_code)

        w = (decay**rank) * tier * q
        pts = 3.0 if match.result == "W" else (1.0 if match.result == "D" else 0.0)

        # Feature 26 (R2): xG-diff when available, gol-diff as fallback per match.
        # use_xg=False → always gol-diff → identical to F16 (R3, tol 1e-9).
        if use_xg and match.xg_for is not None and match.xg_against is not None:
            gd_signal = match.xg_for - match.xg_against
        else:
            gd_signal = float(match.gf - match.ga)

        gf_sum += w * match.gf
        ga_sum += w * match.ga
        gd_sum += w * gd_signal
        ppg_sum += w * pts
        total_w += w

    # total_w > 0 guaranteed when window is non-empty (decay, tier, q all positive)
    return FormMetrics(
        gf_w=gf_sum / total_w,
        ga_w=ga_sum / total_w,
        gd_w=gd_sum / total_w,
        ppg_w=ppg_sum / total_w,
        streak="".join(m.result for m in reversed(window)),
    )
