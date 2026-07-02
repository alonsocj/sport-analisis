"""Selecciones del Mundial 2026 (R8).

Lista parametrizable de las 48 selecciones, con las anfitrionas (México, USA, Canadá)
marcadas como ``host`` para la localía parametrizada en features posteriores. El resto
juega en sede neutral en Norteamérica.

Lista VERIFICADA por el Leader (2026-06-09) contra el calendario real del Mundial 2026
presente en el dataset público ``martj42/international_results`` (72 partidos de fase de
grupos): los 48 nombres aparecen literales en el dataset. Los códigos siguen FIFA (3 letras).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    name: str
    code: str          # código FIFA de 3 letras
    confederation: str
    host: bool = False  # True solo para anfitrionas (localía parametrizada)


# 48 selecciones. host=True -> MEX, USA, CAN.
TEAMS: tuple[Team, ...] = (
    # CONCACAF (6, incluye 3 anfitrionas)
    Team("United States", "USA", "CONCACAF", host=True),
    Team("Mexico", "MEX", "CONCACAF", host=True),
    Team("Canada", "CAN", "CONCACAF", host=True),
    Team("Panama", "PAN", "CONCACAF"),
    Team("Curaçao", "CUW", "CONCACAF"),
    Team("Haiti", "HAI", "CONCACAF"),
    # UEFA (16)
    Team("Spain", "ESP", "UEFA"),
    Team("France", "FRA", "UEFA"),
    Team("England", "ENG", "UEFA"),
    Team("Portugal", "POR", "UEFA"),
    Team("Belgium", "BEL", "UEFA"),
    Team("Netherlands", "NED", "UEFA"),
    Team("Croatia", "CRO", "UEFA"),
    Team("Germany", "GER", "UEFA"),
    Team("Switzerland", "SUI", "UEFA"),
    Team("Austria", "AUT", "UEFA"),
    Team("Turkey", "TUR", "UEFA"),
    Team("Norway", "NOR", "UEFA"),
    Team("Bosnia and Herzegovina", "BIH", "UEFA"),
    Team("Czech Republic", "CZE", "UEFA"),
    Team("Scotland", "SCO", "UEFA"),
    Team("Sweden", "SWE", "UEFA"),
    # CONMEBOL (6)
    Team("Argentina", "ARG", "CONMEBOL"),
    Team("Brazil", "BRA", "CONMEBOL"),
    Team("Uruguay", "URU", "CONMEBOL"),
    Team("Colombia", "COL", "CONMEBOL"),
    Team("Ecuador", "ECU", "CONMEBOL"),
    Team("Paraguay", "PAR", "CONMEBOL"),
    # AFC (9)
    Team("Japan", "JPN", "AFC"),
    Team("South Korea", "KOR", "AFC"),
    Team("Iran", "IRN", "AFC"),
    Team("Australia", "AUS", "AFC"),
    Team("Saudi Arabia", "KSA", "AFC"),
    Team("Qatar", "QAT", "AFC"),
    Team("Iraq", "IRQ", "AFC"),
    Team("Uzbekistan", "UZB", "AFC"),
    Team("Jordan", "JOR", "AFC"),
    # CAF (9)
    Team("Morocco", "MAR", "CAF"),
    Team("Senegal", "SEN", "CAF"),
    Team("Egypt", "EGY", "CAF"),
    Team("Algeria", "ALG", "CAF"),
    Team("Tunisia", "TUN", "CAF"),
    Team("Ivory Coast", "CIV", "CAF"),
    Team("Ghana", "GHA", "CAF"),
    Team("Cape Verde", "CPV", "CAF"),
    Team("South Africa", "RSA", "CAF"),
    # OFC (1)
    Team("New Zealand", "NZL", "OFC"),
    # Repechaje intercontinental (1)
    Team("DR Congo", "COD", "Playoff"),
)

HOST_CODES: frozenset[str] = frozenset({"USA", "MEX", "CAN"})


def all_teams() -> tuple[Team, ...]:
    """Las 48 selecciones."""
    return TEAMS


def host_teams() -> tuple[Team, ...]:
    """Las selecciones anfitrionas (juegan en casa)."""
    return tuple(t for t in TEAMS if t.host)


def is_host(code: str) -> bool:
    """True si el código corresponde a una anfitriona."""
    return code.upper() in HOST_CODES
