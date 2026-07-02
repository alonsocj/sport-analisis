"""src/models/importance.py — Mapa de importancia de partido para Dixon-Coles v2 (R1, R2).

Clasifica cada ``tournament`` (string del silver) en un tier de importancia y devuelve
un factor numérico que escala los pesos de decaimiento temporal:
``w_i = exp(−ξ·Δaños) × importance(tournament_i)``.

El mapa es INYECTABLE: se pasa como argumento opcional a ``load_training_data`` /
``fit_dixon_coles``. El default de compatibilidad hacia atrás es el mapa IDENTIDAD
(todas las importancias = 1.0), que reproduce EXACTAMENTE el comportamiento de v1.

Tiers y factores propuestos (v2 — justificación en design.md, R2):
- ``friendly``  → 0.5   (alineaciones experimentales, alta varianza, baja utilidad informativa)
- ``qualifier`` → 1.0   (clasificatorios, Nations League, playoff continental: partidos reales)
- ``continental_final`` → 1.25 (finales de Euro, Copa América, AFCON: máxima selección)
- ``world_cup`` → 1.5   (Copa del Mundo: el evento objetivo)
- ``unknown``   → 1.0   (fallback determinista para torneos no mapeados)

La clasificación se realiza por normalización de substring (lower-strip) sobre la
tabla explícita ``TIER_KEYWORDS`` — sin heurísticas de aprendizaje automático.
"""

from __future__ import annotations

import unicodedata
from typing import Mapping

# ---------------------------------------------------------------------------
# Tiers y factores por defecto (v2)
# ---------------------------------------------------------------------------

#: Factores por tier propuestos para v2.  INYECTABLE: pasar un dict alternativo
#: como ``tier_factors`` en ``classify_tournament`` o en ``build_importance_map``.
TIER_FACTORS: dict[str, float] = {
    "friendly": 0.5,
    "qualifier": 1.0,
    "continental_final": 1.25,
    "world_cup": 1.5,
    "unknown": 1.0,
}

#: Mapa IDENTIDAD: todas las importancias = 1.0.  Reproduces v1 exactamente.
IDENTITY_FACTORS: dict[str, float] = {tier: 1.0 for tier in TIER_FACTORS}

# ---------------------------------------------------------------------------
# Tabla de clasificación por substring (R2, explícita y documentada)
# ---------------------------------------------------------------------------

#: Orden de prioridad de clasificación (más específico primero).
#: Cada entrada es ``(substring_normalizado, tier)``.
#: La primera coincidencia (substring in tournament_normalizado) determina el tier.
TIER_KEYWORDS: tuple[tuple[str, str], ...] = (
    # Clasificatorios y Nations League (máxima prioridad — evita que
    # "FIFA World Cup Qualification" se clasifique como world_cup)
    ("world cup qualification", "qualifier"),
    ("world cup qualify", "qualifier"),
    ("qualifier", "qualifier"),
    ("qualifying", "qualifier"),
    ("qualification", "qualifier"),
    ("nations league", "qualifier"),
    ("nations cup", "qualifier"),
    ("concacaf nations", "qualifier"),
    ("playoff", "qualifier"),
    ("play-off", "qualifier"),
    # Amistosos (antes de copa del mundo para evitar "Friendly Cup" → world_cup)
    ("friendly", "friendly"),
    ("amistoso", "friendly"),
    ("international friendly", "friendly"),
    ("test match", "friendly"),
    # Copa del Mundo (torneo principal, DESPUÉS de clasificatorios y amistosos)
    ("fifa world cup", "world_cup"),
    ("copa mundial", "world_cup"),
    # Finales de torneos continentales mayores
    ("euro", "continental_final"),
    ("copa america", "continental_final"),
    ("african cup", "continental_final"),
    ("africa cup", "continental_final"),
    ("afcon", "continental_final"),
    ("gold cup", "continental_final"),
    ("concacaf gold", "continental_final"),
    ("asian cup", "continental_final"),
    ("afc asian", "continental_final"),
    ("oceania", "continental_final"),
    ("ofc nations", "continental_final"),
)


def classify_tournament(
    tournament: str,
    tier_keywords: tuple[tuple[str, str], ...] = TIER_KEYWORDS,
) -> str:
    """Clasifica un string de torneo en un tier de importancia (R2).

    Normaliza el string (lower + strip) y busca la primera coincidencia de
    substring en ``tier_keywords`` (orden de prioridad explícito).
    Si no hay coincidencia → ``"unknown"`` (fallback determinista, documentado).

    Args:
        tournament: Raw tournament name from silver (e.g. ``"FIFA World Cup"``).
        tier_keywords: Ordered keyword table; injectable for tests.

    Returns:
        Tier string: one of ``"friendly"``, ``"qualifier"``,
        ``"continental_final"``, ``"world_cup"``, ``"unknown"``.
    """
    raw = str(tournament)
    normalized = (
        unicodedata.normalize("NFKD", raw)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )
    for keyword, tier in tier_keywords:
        if keyword in normalized:
            return tier
    return "unknown"


def importance_factor(
    tournament: str,
    tier_factors: Mapping[str, float] = TIER_FACTORS,
    tier_keywords: tuple[tuple[str, str], ...] = TIER_KEYWORDS,
) -> float:
    """Factor de importancia numérico para un torneo (R1, R2).

    Args:
        tournament: Raw tournament name from silver.
        tier_factors: Mapping from tier to numeric factor.  Injectable; use
            ``IDENTITY_FACTORS`` to reproduce v1 behaviour.
        tier_keywords: Ordered keyword table; injectable for tests.

    Returns:
        Float factor >= 0.  Falls back to ``tier_factors["unknown"]`` if the
        tier is not found in ``tier_factors``.
    """
    tier = classify_tournament(tournament, tier_keywords)
    return float(tier_factors.get(tier, tier_factors.get("unknown", 1.0)))


def build_importance_map(
    tournaments: list[str],
    tier_factors: Mapping[str, float] = TIER_FACTORS,
    tier_keywords: tuple[tuple[str, str], ...] = TIER_KEYWORDS,
) -> dict[str, float]:
    """Construye un mapa ``{tournament_raw: factor}`` para una lista de torneos (R1).

    Útil para precalcular el mapa una vez y pasarlo a ``load_training_data`` como
    ``importance_map``, evitando reclasificar en cada partido del loop.

    Args:
        tournaments: Unique tournament names from the silver (may include duplicates;
            the returned dict deduplicates).
        tier_factors: Factor mapping by tier.
        tier_keywords: Ordered keyword table.

    Returns:
        Dict mapping each unique tournament string to its numeric factor.
    """
    return {
        t: importance_factor(t, tier_factors, tier_keywords) for t in set(tournaments)
    }


def identity_importance_map(tournaments: list[str]) -> dict[str, float]:
    """Mapa identidad (todos los factores = 1.0) para una lista de torneos (R1).

    Reproduce EXACTAMENTE el comportamiento v1 cuando se pasa como ``importance_map``
    a ``load_training_data`` / ``fit_dixon_coles``.

    Args:
        tournaments: Tournament names; only used to build the key set.

    Returns:
        Dict with ``{t: 1.0}`` for every unique ``t`` in ``tournaments``.
    """
    return {t: 1.0 for t in set(tournaments)}
