"""Capa gold: ratings Elo por selección (R12–R19).

Fórmula estándar eloratings.net, parametrizable vía ``EloParams`` inyectable:
``elo_post = elo_pre + K · G · (score − We)`` con rating inicial 1500 (R12), ``K`` por
importancia del torneo (R14), multiplicador de margen ``G`` (R15), ventaja de localía
+100 solo en sede no neutral (R16), actualización exactamente simétrica (R13, R17) y
orden cronológico determinista por ``(date, match_id)`` (R18). El Elo se calcula sobre
TODOS los partidos de silver, incluidos equipos fuera de las 48 (R19).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

# Reglas K por defecto (R14): lista ORDENADA de (patrones substring case-insensitive, K);
# gana la primera regla cuyos patrones aparezcan TODOS en el nombre del torneo. La
# precedencia "world cup" + "qualif" (50) ANTES que "world cup" (60) evita que
# "FIFA World Cup qualification" capture el K del Mundial.
DEFAULT_K_RULES: tuple[tuple[tuple[str, ...], float], ...] = (
    (("world cup", "qualif"), 50.0),  # eliminatorias mundialistas
    (("world cup",), 60.0),  # Mundial (fase final)
    (("nations league",), 40.0),  # UEFA/CONCACAF Nations League
    (("confederations cup",), 40.0),  # Copa Confederaciones
    (("copa américa",), 50.0),  # continentales = 50
    (("copa america",), 50.0),
    (("uefa euro",), 50.0),
    (("african cup of nations",), 50.0),
    (("africa cup of nations",), 50.0),
    (("asian cup",), 50.0),
    (("gold cup",), 50.0),
    (("concacaf championship",), 50.0),
    (("ofc nations cup",), 50.0),
    (("friendl",), 20.0),  # "Friendly" (público) y "Friendlies" (API)
)

# Contrato de ``data/gold/elo_history.csv`` (R19): una fila por equipo y partido.
HISTORY_COLUMNS: tuple[str, ...] = (
    "date",
    "code",
    "opponent_code",
    "elo_pre",
    "elo_post",
    "k",
    "g",
    "we",
    "score",
)


@dataclass(frozen=True)
class EloParams:
    """Parámetros inyectables del Elo (R12, R14, R16)."""

    initial: float = 1500.0  # R12: rating al primer partido de cada equipo
    home_advantage: float = 100.0  # R16: se suma a dr SOLO si neutral == False
    default_k: float = 30.0  # R14: K cuando ninguna regla coincide
    k_rules: tuple[tuple[tuple[str, ...], float], ...] = DEFAULT_K_RULES


def k_for_tournament(tournament: str | None, params: EloParams | None = None) -> float:
    """``K`` por importancia del torneo: primera regla coincidente gana (R14)."""
    params = params or EloParams()
    name = (tournament or "").lower()
    for patterns, k in params.k_rules:
        if all(pattern in name for pattern in patterns):
            return k
    return params.default_k


def margin_multiplier(home_goals: int, away_goals: int) -> float:
    """Multiplicador por margen de goles ``G`` (R15).

    ``diff = |home_goals − away_goals|``: ``diff <= 1 → 1.0``; ``diff == 2 → 1.5``;
    ``diff >= 3 → (11 + diff) / 8``.
    """
    diff = abs(home_goals - away_goals)
    if diff <= 1:
        return 1.0
    if diff == 2:
        return 1.5
    return (11 + diff) / 8


def expected_home(
    elo_home: float,
    elo_away: float,
    neutral: bool,
    params: EloParams | None = None,
) -> float:
    """Expectativa del local ``We = 1 / (1 + 10^(−dr/400))`` (R16).

    ``dr = elo_home − elo_away + home_advantage`` SI ``neutral == False``;
    sin la ventaja SI ``neutral == True``.
    """
    params = params or EloParams()
    dr = elo_home - elo_away + (0.0 if neutral else params.home_advantage)
    return 1.0 / (1.0 + 10.0 ** (-dr / 400.0))


def run_elo(
    matches: pd.DataFrame,
    params: EloParams | None = None,
) -> tuple[dict[str, float], pd.DataFrame]:
    """Procesa todos los partidos y devuelve ``(ratings finales, historial)`` (R12–R19).

    - Orden de proceso: ascendente por ``(date, match_id)`` — desempate determinista en
      la misma fecha; misma entrada → mismos ratings e historial (R18).
    - Primer partido de un equipo → rating ``params.initial`` (R12).
    - ``elo_post = elo_pre + K · G · (score − We)`` por lado, con el MISMO ``K`` y ``G``;
      ``delta_away = −delta_home`` ⇒ suma de cambios exactamente 0 (R13, R17).
    - Alcance global: incluye equipos fuera de las 48 (códigos slug) (R19).
    - Historial: 2 filas por partido (lado local primero) con ``we`` y ``score`` del
      equipo de la fila (R19).
    """
    params = params or EloParams()
    ordered = matches.sort_values(["date", "match_id"], kind="mergesort")
    ratings: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    for match in ordered.itertuples(index=False):
        home, away = match.home_code, match.away_code
        elo_home = ratings.get(home, params.initial)
        elo_away = ratings.get(away, params.initial)
        k = k_for_tournament(match.tournament, params)
        g = margin_multiplier(int(match.home_goals), int(match.away_goals))
        we_home = expected_home(elo_home, elo_away, bool(match.neutral), params)
        if match.home_goals > match.away_goals:
            score_home = 1.0
        elif match.home_goals < match.away_goals:
            score_home = 0.0
        else:
            score_home = 0.5
        delta_home = k * g * (score_home - we_home)  # R13
        post_home = elo_home + delta_home
        post_away = elo_away - delta_home  # R17: simetría exacta
        rows.append(
            {
                "date": match.date,
                "code": home,
                "opponent_code": away,
                "elo_pre": elo_home,
                "elo_post": post_home,
                "k": k,
                "g": g,
                "we": we_home,
                "score": score_home,
            }
        )
        rows.append(
            {
                "date": match.date,
                "code": away,
                "opponent_code": home,
                "elo_pre": elo_away,
                "elo_post": post_away,
                "k": k,
                "g": g,
                "we": 1.0 - we_home,
                "score": 1.0 - score_home,
            }
        )
        ratings[home] = post_home
        ratings[away] = post_away
    history = pd.DataFrame(rows, columns=list(HISTORY_COLUMNS))
    return ratings, history


def ratings_as_of(history: pd.DataFrame, as_of_date: str) -> dict[str, float]:
    """Rating vigente por equipo a ``as_of_date``: replay con ``date < as_of_date`` (R19, R20).

    Precondición: ``history`` en el orden cronológico producido por ``run_elo``.
    Equipos sin partidos previos no aparecen (el caller usa ``params.initial``).
    """
    out: dict[str, float] = {}
    prev = history[history["date"] < as_of_date]
    for row in prev.itertuples(index=False):
        out[row.code] = float(row.elo_post)
    return out
