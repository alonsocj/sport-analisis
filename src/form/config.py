"""Configuración versionada de parámetros para la feature forma_reciente (Feature 16).

Todos los parámetros son explícitos y documentados. Ver design.md para la
justificación de cada valor.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormConfig:
    """Parámetros del módulo de forma reciente (design.md).

    Attributes:
        k_pre: Maximum number of pre-WC matches to include per team (default 5).
        decay: Exponential recency decay; W_i = decay^rank_i, rank 0 = most recent.
            (default 0.85: suave, no colapsa a 1 partido)
        tier_ratio: WC group match weight multiplier vs pre-WC friendly.
            (default 2.0: competitivo > friendly)
        opp_elo_pivot: Reference Elo for opponent quality adjustment (default 1500).
        opp_scale: Elo scale for quality clip, q = clip(1 + (elo-pivot)/scale, 0.5, 2.0).
            (default 400: escala Elo estándar)
    """

    k_pre: int = 5
    decay: float = 0.85
    tier_ratio: float = 2.0
    opp_elo_pivot: float = 1500.0
    opp_scale: float = 400.0


#: Default configuration instance — todos los defaults del design.md.
DEFAULT_FORM_CONFIG: FormConfig = FormConfig()

#: Fecha de inicio del Mundial 2026 (para clasificar partido de grupo vs pre-WC).
WC2026_START_DATE: str = "2026-06-11"

#: Nombre del torneo en el silver matches CSV (contrato feature 2).
WC_TOURNAMENT: str = "FIFA World Cup"
