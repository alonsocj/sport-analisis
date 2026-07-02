"""Capa gold: medias móviles de los últimos 15 partidos por equipo y métrica (R8–R11).

Desde silver se construye una vista larga (2 filas por partido, una por equipo) y, para
una ``as_of_date`` inyectada, se promedian las últimas hasta 15 observaciones NO nulas de
cada métrica usando SOLO partidos con fecha estrictamente anterior (anti-leakage, R9).
Fechas como string ISO ``YYYY-MM-DD`` comparadas lexicográficamente (orden válido).
"""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

# Ventana por defecto (R8): últimas hasta 15 observaciones.
ROLLING_WINDOW: int = 15

# Métrica en perspectiva de equipo → columna feature del contrato gold (R8, R20).
_METRIC_TO_FEATURE: tuple[tuple[str, str], ...] = (
    ("gf", "gf_ma15"),
    ("ga", "ga_ma15"),
    ("corners_for", "corners_for_ma15"),
    ("corners_against", "corners_against_ma15"),
    ("cards", "cards_ma15"),
    ("shots", "shots_ma15"),
    ("shots_on_target", "shots_on_target_ma15"),
    ("possession", "possession_ma15"),
)

FEATURE_COLUMNS: tuple[str, ...] = tuple(feature for _, feature in _METRIC_TO_FEATURE)


def long_view(silver: pd.DataFrame) -> pd.DataFrame:
    """Vista larga desde silver: 2 filas por partido, métricas en perspectiva de equipo (R8).

    ``gf``/``ga`` (goles a favor/en contra), ``corners_for``/``corners_against``
    (córners propios/del rival), ``cards``, ``shots``, ``shots_on_target`` y
    ``possession`` del lado propio.
    """
    sides: list[pd.DataFrame] = []
    for own, opp in (("home", "away"), ("away", "home")):
        sides.append(
            pd.DataFrame(
                {
                    "match_id": silver["match_id"],
                    "date": silver["date"],
                    "code": silver[f"{own}_code"],
                    "gf": silver[f"{own}_goals"],
                    "ga": silver[f"{opp}_goals"],
                    "corners_for": silver[f"{own}_corners"],
                    "corners_against": silver[f"{opp}_corners"],
                    "cards": silver[f"{own}_cards"],
                    "shots": silver[f"{own}_shots"],
                    "shots_on_target": silver[f"{own}_shots_on_target"],
                    "possession": silver[f"{own}_possession"],
                }
            )
        )
    return pd.concat(sides, ignore_index=True)


def team_features(
    long_df: pd.DataFrame,
    code: str,
    as_of_date: str,
    window: int = ROLLING_WINDOW,
) -> dict[str, Any]:
    """Features de medias móviles de un equipo a una ``as_of_date`` (R8–R11).

    - Solo partidos con ``date < as_of_date`` estricto (R9: el propio partido y los
      futuros quedan excluidos).
    - Por métrica: media de las últimas hasta ``window`` observaciones no nulas (R8);
      sin observaciones → null (R10, R11).
    - ``matches_count`` = ``min(window, partidos previos)`` sobre la ventana de goles
      (``gf``/``ga`` nunca son nulos en silver); 0 partidos → todas las medias null y
      ``matches_count = 0``, sin fallar (R10).
    """
    prev = long_df[(long_df["code"] == code) & (long_df["date"] < as_of_date)]
    prev = prev.sort_values(["date", "match_id"], kind="mergesort")
    out: dict[str, Any] = {
        "code": code,
        "matches_count": int(min(window, len(prev))),
    }
    for metric, feature in _METRIC_TO_FEATURE:
        observations = prev[metric].dropna().tail(window)
        out[feature] = float(observations.mean()) if len(observations) else None
    return out


def compute_rolling_features(
    silver: pd.DataFrame,
    codes: Iterable[str],
    as_of_date: str,
    window: int = ROLLING_WINDOW,
) -> pd.DataFrame:
    """Features de medias móviles para varios equipos, ordenados por ``code`` (R8–R11)."""
    lv = long_view(silver)
    rows = [team_features(lv, code, as_of_date, window) for code in sorted(codes)]
    df = pd.DataFrame(rows, columns=["code", "matches_count", *FEATURE_COLUMNS])
    for col in FEATURE_COLUMNS:
        df[col] = df[col].astype(float)
    return df
