"""src/ingestion/fotmob_halves.py — Feature 32: ingesta per-mitad desde fotmob.

Extrae, por partido fotmob, las stats de ``Periods.FirstHalf``/``SecondHalf``
(además del ``All`` que ya lee ``fotmob_stats.parse_match_stats``) y los eventos
de gol con minuto (``content.matchFacts.events.events``), para construir la señal
de tendencia por mitad (1T/2T).

Reutiliza los helpers de ``fotmob_stats`` (``_extract_next_data``,
``_extract_team_stats``) — cero red en tests (transporte inyectable en el caller).
"""

from __future__ import annotations

from typing import Any

from .fotmob_stats import _extract_next_data, _extract_team_stats

# Periodos fotmob que nos interesan (regulación); ``All`` incluye tiempo extra.
_PERIODS: tuple[str, ...] = ("All", "FirstHalf", "SecondHalf")


def parse_periods(html: str) -> dict[str, dict[str, dict[str, float | None]]]:
    """Extrae las stats por periodo (All/FirstHalf/SecondHalf) del HTML fotmob (R1).

    Reutiliza ``_extract_team_stats`` (mismo mapeo de títulos y suma de tarjetas
    que ``parse_match_stats``) aplicándolo a cada periodo.

    Args:
        html: HTML de la página de partido de fotmob.

    Returns:
        Dict ``{periodo: {"home": {stat: val}, "away": {stat: val}}}`` SOLO para los
        periodos con stats disponibles. Un partido viejo con solo ``Periods.All``
        devuelve únicamente la clave ``"All"`` (retrocompatibilidad).
    """
    data = _extract_next_data(html)
    page_props = (data.get("props") or {}).get("pageProps", {})
    content = page_props.get("content") or {}
    periods = (content.get("stats") or {}).get("Periods") or {}

    out: dict[str, dict[str, dict[str, float | None]]] = {}
    for name in _PERIODS:
        groups = (periods.get(name) or {}).get("stats") or []
        if not groups:
            continue
        home, away = _extract_team_stats(groups)
        out[name] = {"home": home, "away": away}
    return out


def parse_goal_events(html: str) -> list[dict[str, Any]]:
    """Extrae los eventos de gol (con minuto) del HTML fotmob (R1).

    Lee ``content.matchFacts.events.events`` y conserva solo ``type == "Goal"``.
    Ignora otros eventos (Half, AddedTime, Card, Substitution, penaltyShootout, …).

    Args:
        html: HTML de la página de partido de fotmob.

    Returns:
        Lista de dicts ``{minute, stoppage, is_home, own_goal, player}`` en orden.
    """
    data = _extract_next_data(html)
    page_props = (data.get("props") or {}).get("pageProps", {})
    content = page_props.get("content") or {}
    events = ((content.get("matchFacts") or {}).get("events") or {}).get("events") or []

    goals: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("type") != "Goal":
            continue
        player = ev.get("player") or {}
        goals.append(
            {
                "minute": ev.get("time"),
                "stoppage": ev.get("overloadTime") or 0,
                "is_home": ev.get("isHome"),
                "own_goal": bool(ev.get("ownGoal")),
                "player": player.get("name") or ev.get("nameStr"),
            }
        )
    return goals


def attribute_goals(
    goals: list[dict[str, Any]], home_code: str, away_code: str
) -> list[tuple[str, str]]:
    """Asigna cada gol a (código de equipo, mitad) según ``is_home`` (R2).

    Args:
        goals: Salida de ``parse_goal_events``.
        home_code: Código FIFA del equipo local.
        away_code: Código FIFA del equipo visitante.

    Returns:
        Lista de tuplas ``(team_code, half)`` — el equipo al que se le acredita el
        gol en el marcador (``is_home`` True → local) y su mitad (``half_of``).
    """
    out: list[tuple[str, str]] = []
    for g in goals:
        team = home_code if g.get("is_home") else away_code
        out.append((team, half_of(int(g["minute"]))))
    return out


def half_of(minute: int) -> str:
    """Clasifica un minuto de gol en su mitad de regulación (R2).

    Args:
        minute: Minuto del gol (fotmob: 1..90 con stoppage plegado, >90 = tiempo extra).

    Returns:
        ``"1T"`` si minuto ≤ 45, ``"2T"`` si 46 ≤ minuto ≤ 90, ``"ET"`` si > 90.
    """
    if minute <= 45:
        return "1T"
    if minute <= 90:
        return "2T"
    return "ET"
