"""Módulo de forma reciente (Feature 16): ventana, métricas y factor multiplicativo.

Ajuste de la fuerza prospectiva del modelo Dixon-Coles v1 mediante un factor
multiplicativo sobre las λ en inferencia. No reentrena el modelo; es reversible
y medible vs v1. Default γ=0 → no-regresión exacta (tol 1e-9).

APIs públicas:
- ``build_window``: ventana de partidos recientes por equipo (anti-fuga, R1).
- ``team_form``: métricas ponderadas por recencia y calidad de rival (R2, R3).
- ``make_form_factor_fn``: callable form_factor(home, away) → (mult_home, mult_away) (R4).
- ``make_form_factory``: factory(as_of) → form_factor_fn para backtest walk-forward (R5).
- ``FormConfig``, ``DEFAULT_FORM_CONFIG``: configuración versionada (design.md).
- ``MatchInWindow``, ``FormMetrics``: tipos de datos.
"""

from .config import DEFAULT_FORM_CONFIG, FormConfig, WC2026_START_DATE, WC_TOURNAMENT
from .factor import FormFactoryFn, FormFactorFn, make_form_factor_fn, make_form_factory
from .metrics import FormMetrics, team_form
from .window import MatchInWindow, build_window

__all__ = [
    "DEFAULT_FORM_CONFIG",
    "FormConfig",
    "FormFactoryFn",
    "FormFactorFn",
    "FormMetrics",
    "MatchInWindow",
    "WC2026_START_DATE",
    "WC_TOURNAMENT",
    "build_window",
    "make_form_factor_fn",
    "make_form_factory",
    "team_form",
]
