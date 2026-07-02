"""Construcción de la ventana de forma reciente por equipo (R1, Feature 16).

La ventana es leak-free: solo incluye partidos con ``date < as_of`` (estricto).
El partido a predecir nunca entra en su propia ventana (anti-fuga, R4).
Ventana parcial sin abortar si no hay partidos en algún tramo (R1).

Feature 18 (forma_perf): indexación en una sola pasada vía
``index_matches_by_team`` + ``build_window_from_bucket``.  La API pública
``build_window`` se conserva intacta (R3).

Feature 26 (forma_xg): ``MatchInWindow`` añade campos opcionales ``xg_for``/
``xg_against`` poblados desde ``home_xg``/``away_xg`` del silver (R1). Partidos
sin xG (NaN/null) → None (fallback a goles en ``team_form``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from .config import WC2026_START_DATE, WC_TOURNAMENT


@dataclass(frozen=True)
class MatchInWindow:
    """Un partido dentro de la ventana de forma reciente (R1).

    Attributes:
        date: Match date string (YYYY-MM-DD).
        is_group_wc: True if this is a WC2026 group-stage match.
        gf: Goals scored by the team.
        ga: Goals conceded by the team.
        opp_code: FIFA code of the opponent.
        result: Match result from the team's perspective: 'W', 'D', or 'L'.
        xg_for: Expected goals for the team (Feature 26, F23 fotmob). None if not
            available (pre-WC or not yet scraped).
        xg_against: Expected goals against the team (Feature 26, F23 fotmob). None
            if not available.
    """

    date: str
    is_group_wc: bool
    gf: int
    ga: int
    opp_code: str
    result: Literal["W", "D", "L"]
    xg_for: float | None = None
    xg_against: float | None = None


# ---------------------------------------------------------------------------
# Funciones puras compartidas (Feature 18 — extraídas para reuso)
# ---------------------------------------------------------------------------

def _compute_result(gf: int, ga: int) -> Literal["W", "D", "L"]:
    """Devuelve el resultado desde la perspectiva del equipo con gf goles marcados.

    Args:
        gf: Goals scored by the team.
        ga: Goals conceded by the team.

    Returns:
        'W', 'D', or 'L'.
    """
    if gf > ga:
        return "W"
    if gf < ga:
        return "L"
    return "D"


def _make_record(
    match_date: str,
    tournament: str,
    home_code: str,
    away_code: str,
    home_g: int,
    away_g: int,
    team: str,
    home_xg: float | None = None,
    away_xg: float | None = None,
) -> MatchInWindow:
    """Construye un MatchInWindow desde la perspectiva de ``team``.

    Shared logic for both the single-team and indexed paths to guarantee
    identical results (R2, Feature 18).  Feature 26 adds ``xg_for``/
    ``xg_against`` from ``home_xg``/``away_xg`` (None when unavailable).

    Args:
        match_date: Date string (YYYY-MM-DD).
        tournament: Tournament name string.
        home_code: FIFA code of the home team.
        away_code: FIFA code of the away team.
        home_g: Goals scored by the home team.
        away_g: Goals scored by the away team.
        team: Team for which to build the perspective (home_code or away_code).
        home_xg: Expected goals for the home team (Feature 26). None if unavailable.
        away_xg: Expected goals for the away team (Feature 26). None if unavailable.

    Returns:
        MatchInWindow from team's perspective.
    """
    is_wc2026_group = (tournament == WC_TOURNAMENT) and (match_date >= WC2026_START_DATE)
    if team == home_code:
        gf, ga, opp = home_g, away_g, away_code
        xg_for, xg_against = home_xg, away_xg
    else:
        gf, ga, opp = away_g, home_g, home_code
        xg_for, xg_against = away_xg, home_xg
    return MatchInWindow(
        date=match_date,
        is_group_wc=is_wc2026_group,
        gf=gf,
        ga=ga,
        opp_code=opp,
        result=_compute_result(gf, ga),
        xg_for=xg_for,
        xg_against=xg_against,
    )


def index_matches_by_team(
    matches: pd.DataFrame,
    teams: list[str],
) -> dict[str, list[MatchInWindow]]:
    """Indexa partidos por equipo en UNA sola pasada (R1, Feature 18).

    Traverses the DataFrame once with ``itertuples`` (not ``iterrows``) and
    groups MatchInWindow records per team.  Rows with non-numeric goals are
    silently skipped.  Records are stored in DataFrame row order so that
    subsequent stable sorts reproduce the same relative ordering as the
    original single-team ``build_window`` (equivalence guarantee, R2).

    Args:
        matches: Silver matches DataFrame.  Required columns: date,
            home_code, away_code, home_goals, away_goals, tournament.
        teams: List of FIFA team codes to index.  Only rows where
            home_code or away_code is in this list are stored.

    Returns:
        Dict mapping each team code to its list of MatchInWindow records
        (unfiltered by as_of — filtering happens in build_window_from_bucket).
    """
    teams_set: set[str] = set(teams)
    index: dict[str, list[MatchInWindow]] = {t: [] for t in teams}

    for row in matches.itertuples(index=False):
        home = str(row.home_code) if hasattr(row, "home_code") else ""
        away = str(row.away_code) if hasattr(row, "away_code") else ""

        home_in = home in teams_set
        away_in = away in teams_set
        if not home_in and not away_in:
            continue

        match_date = str(row.date) if hasattr(row, "date") else ""
        if not match_date:
            continue

        # Parse goals; skip if non-numeric (partido no jugado o datos faltantes)
        try:
            home_g = int(float(row.home_goals))
            away_g = int(float(row.away_goals))
        except (ValueError, TypeError, AttributeError):
            continue

        tournament = str(row.tournament) if hasattr(row, "tournament") else ""

        # Feature 26 (forma_xg): read home_xg/away_xg; NaN or missing → None (R1).
        home_xg: float | None = None
        away_xg: float | None = None
        if hasattr(row, "home_xg"):
            try:
                _hxg = float(row.home_xg)
                if not math.isnan(_hxg):
                    home_xg = _hxg
            except (TypeError, ValueError):
                pass
        if hasattr(row, "away_xg"):
            try:
                _axg = float(row.away_xg)
                if not math.isnan(_axg):
                    away_xg = _axg
            except (TypeError, ValueError):
                pass

        if home_in:
            index[home].append(
                _make_record(match_date, tournament, home, away, home_g, away_g, home, home_xg, away_xg)
            )
        if away_in:
            index[away].append(
                _make_record(match_date, tournament, home, away, home_g, away_g, away, home_xg, away_xg)
            )

    return index


def build_window_from_bucket(
    bucket: list[MatchInWindow],
    as_of: str,
    k_pre: int = 5,
) -> list[MatchInWindow]:
    """Construye la ventana de forma desde el bucket pre-indexado de un equipo (R1, Feature 18).

    Applies the same selection logic as ``build_window``:
    strict date < as_of, up to 3 WC-group + up to k_pre pre-WC, ascending order.

    Args:
        bucket: Pre-built list of MatchInWindow for one team (all dates, no
            as_of filter applied yet).
        as_of: Cutoff date (exclusive, strict).  Matches with date >= as_of excluded.
        k_pre: Maximum number of pre-WC matches to include (default 5).

    Returns:
        List of MatchInWindow sorted ascending by date (oldest first).
    """
    wc_group: list[MatchInWindow] = []
    pre_wc: list[MatchInWindow] = []

    for record in bucket:
        if record.date >= as_of:
            continue  # strict: date < as_of (anti-fuga)
        if record.is_group_wc:
            wc_group.append(record)
        else:
            pre_wc.append(record)

    # Sort each tranche ascending by date, take most recent K
    wc_group.sort(key=lambda m: m.date)
    pre_wc.sort(key=lambda m: m.date)

    wc_selected = wc_group[-3:] if len(wc_group) > 3 else wc_group
    pre_selected = pre_wc[-k_pre:] if len(pre_wc) > k_pre else pre_wc

    # Combine and sort ascending by date (oldest first)
    return sorted(wc_selected + pre_selected, key=lambda m: m.date)


# ---------------------------------------------------------------------------
# API pública — firma estable (R3, Feature 16 + Feature 18)
# ---------------------------------------------------------------------------

def build_window(
    matches: pd.DataFrame,
    team: str,
    as_of: str,
    k_pre: int = 5,
) -> list[MatchInWindow]:
    """Construye la ventana de forma reciente para ``team`` antes de ``as_of`` (R1).

    Includes two tranches, always with date < as_of (strict anti-fuga):
    - (a) Up to 3 most recent WC2026 group matches (tournament == WC_TOURNAMENT,
          date >= WC2026_START_DATE).
    - (b) Up to k_pre most recent pre-WC matches (date < WC2026_START_DATE).

    Matches with non-numeric goals are silently skipped (not played or missing data).
    If a team has no matches in a tranche, that tranche is empty (no error raised, R1).
    Result is sorted ascending by date (oldest first).

    Feature 18: re-implemented on top of ``index_matches_by_team`` +
    ``build_window_from_bucket`` to share logic and guarantee equivalence.
    Public signature and return value are unchanged (R3).

    Args:
        matches: Silver matches DataFrame. Required columns: date, home_code,
            away_code, home_goals, away_goals, tournament.
        team: FIFA team code to build the window for.
        as_of: Cutoff date (exclusive, strict). Matches with date >= as_of excluded.
        k_pre: Maximum number of pre-WC matches to include (default 5).

    Returns:
        List of MatchInWindow sorted ascending by date (oldest first).
    """
    index = index_matches_by_team(matches, [team])
    bucket = index.get(team, [])
    return build_window_from_bucket(bucket, as_of, k_pre)
