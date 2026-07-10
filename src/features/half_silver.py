"""src/features/half_silver.py — Feature 32, R3: tabla silver por-mitad.

Construye, por partido y equipo, filas por mitad (1T/2T) con goles for/against,
xG for/against y tiros for/against (donde haya cobertura fotmob). Combina:
- goles por minuto (de los eventos fotmob o de ``goalscorers.csv`` pre-torneo),
- stats per-mitad (de ``parse_periods``; null si el partido no fue scrapeado).

Determinista, sin red, anti-fuga (``date < as_of``).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.ingestion.fotmob_halves import half_of

# Mitades de regulación (ET se registra pero no es una "mitad" del reparto de mercado).
_HALVES: tuple[str, ...] = ("1T", "2T")


def _goals_by_side_half(goals: list[dict[str, Any]]) -> dict[tuple[bool, str], int]:
    """Cuenta goles por (is_home, mitad). ET incluida por completitud."""
    counts: dict[tuple[bool, str], int] = {}
    for g in goals:
        key = (bool(g.get("is_home")), half_of(int(g["minute"])))
        counts[key] = counts.get(key, 0) + 1
    return counts


def match_half_rows(
    match_id: str,
    date: str,
    home_code: str,
    away_code: str,
    periods: dict[str, dict[str, dict[str, float | None]]],
    goals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filas por (equipo, mitad) de un partido (R3).

    Args:
        match_id: Id del partido.
        date: Fecha YYYY-MM-DD.
        home_code / away_code: Códigos FIFA local/visitante.
        periods: Salida de ``parse_periods`` (puede venir sin FirstHalf/SecondHalf).
        goals: Salida de ``parse_goal_events``.

    Returns:
        Lista de 4 dicts (home×{1T,2T}, away×{1T,2T}) con gf/ga/xg/shots/cover_xg.
        ET no genera fila (fuera de la regulación); sus goles no cuentan en 1T/2T.
    """
    counts = _goals_by_side_half(goals)
    period_key = {"1T": "FirstHalf", "2T": "SecondHalf"}

    rows: list[dict[str, Any]] = []
    for is_home, team_code, opp_is_home in (
        (True, home_code, False),
        (False, away_code, True),
    ):
        side = "home" if is_home else "away"
        opp_side = "away" if is_home else "home"
        for half in _HALVES:
            per = periods.get(period_key[half]) or {}
            cover = bool(per)
            team_stats = (per.get(side) or {}) if cover else {}
            opp_stats = (per.get(opp_side) or {}) if cover else {}
            rows.append(
                {
                    "match_id": match_id,
                    "date": date,
                    "team_code": team_code,
                    "is_home": is_home,
                    "half": half,
                    "gf": counts.get((is_home, half), 0),
                    "ga": counts.get((opp_is_home, half), 0),
                    "xg_for": team_stats.get("xg") if cover else None,
                    "xg_against": opp_stats.get("xg") if cover else None,
                    "shots_for": team_stats.get("shots") if cover else None,
                    "shots_against": opp_stats.get("shots") if cover else None,
                    "cover_xg": cover,
                }
            )
    return rows


def build_silver_por_mitad(matches: list[dict[str, Any]], as_of: str) -> pd.DataFrame:
    """Tabla silver por-mitad de todos los partidos con ``date < as_of`` (R3, anti-fuga).

    Args:
        matches: Lista de dicts con match_id/date/home_code/away_code/periods/goals.
        as_of: Fecha de corte (YYYY-MM-DD); solo partidos ESTRICTAMENTE anteriores.

    Returns:
        DataFrame con una fila por (equipo, mitad).
    """
    rows: list[dict[str, Any]] = []
    for m in matches:
        if str(m["date"]) >= str(as_of):  # anti-fuga: date < as_of
            continue
        rows.extend(
            match_half_rows(
                m["match_id"],
                m["date"],
                m["home_code"],
                m["away_code"],
                m.get("periods") or {},
                m.get("goals") or [],
            )
        )
    cols = [
        "match_id", "date", "team_code", "is_home", "half",
        "gf", "ga", "xg_for", "xg_against", "shots_for", "shots_against", "cover_xg",
    ]
    return pd.DataFrame(rows, columns=cols)
