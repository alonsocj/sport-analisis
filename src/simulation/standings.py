"""src/simulation/standings.py — Tabla de grupo con desempates deterministas (R4).

Responsabilidades:
- ``compute_group_table``: calcula puntos 3/1/0 y desempates deterministas.
- ``rank_third_places``: ranking global de los 12 terceros para seleccionar los 8 mejores.

Desempates (documentados, R4):
Orden determinista para clasificar dentro de un grupo:
  1. Puntos (3/win, 1/draw, 0/loss).
  2. Diferencia de goles global (GF − GA).
  3. Goles a favor (GF).
  4. Criterio final reproducible sin azar: fuerza de ataque del modelo (parámetro
     opcional ``attack_strength``); si no se proporciona, desempate por orden
     alfabético del código FIFA (estable y determinista).

SIMPLIFICACIONES DOCUMENTADAS respecto al reglamento FIFA completo (R4):
- Head-to-head (puntos, DG y GF entre los empatados): NO implementado — excede
  la complejidad de la simulación y requiere seguimiento granular por par.
- Fair-play (tarjetas): NO implementado — sin datos de tarjetas en la simulación.
- Sorteo: NO implementado — se usa orden alfabético como criterio terminal.
Los desempates implementados son deterministas y reproducibles, garantizando
que el mismo marcador produzca siempre el mismo ranking.

Ranking de terceros (R4):
Los 12 terceros se clasifican por los mismos criterios (puntos, DG, GF, fuerza/alfabético).
Los 8 mejores avanzan a R32.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .bracket import GroupFixture


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------

@dataclass
class TeamStanding:
    """Posición de un equipo en la tabla del grupo.

    Args:
        team: FIFA team code.
        played: Matches played.
        wins: Matches won.
        draws: Matches drawn.
        losses: Matches lost.
        gf: Goals scored (for).
        ga: Goals conceded (against).
        points: Points accumulated (3/1/0).
        attack_strength: Optional model attack parameter for tiebreaking.
    """
    team: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    gf: int = 0
    ga: int = 0
    points: int = 0
    attack_strength: float = 0.0

    @property
    def gd(self) -> int:
        """Goal difference (GF − GA)."""
        return self.gf - self.ga


# ---------------------------------------------------------------------------
# Cálculo de la tabla de grupo
# ---------------------------------------------------------------------------

def compute_group_table(
    teams: Sequence[str],
    fixtures: Sequence[GroupFixture],
    attack_strength: dict[str, float] | None = None,
) -> list[TeamStanding]:
    """Calcula la tabla de grupo a partir de los marcadores de los fixtures (R4).

    Sólo procesa fixtures con marcadores no-``None`` (los pendientes no afectan
    la tabla hasta que se simulan).

    Args:
        teams: Sequence of 4 FIFA team codes in the group.
        fixtures: All 6 group-stage fixtures (some may have ``None`` scores).
        attack_strength: Optional dict mapping team code to model attack parameter.
            Used as tiebreaker criterion 4. ``None`` → alphabetical order.

    Returns:
        List of 4 TeamStanding objects sorted by the deterministic tiebreak rules.
    """
    standings: dict[str, TeamStanding] = {
        t: TeamStanding(
            team=t,
            attack_strength=attack_strength.get(t, 0.0) if attack_strength else 0.0,
        )
        for t in teams
    }

    for fix in fixtures:
        if fix.home_goals is None or fix.away_goals is None:
            continue  # fixture pendiente: no afecta la tabla

        home_g = int(fix.home_goals)
        away_g = int(fix.away_goals)

        s_home = standings[fix.home]
        s_away = standings[fix.away]

        s_home.played += 1
        s_away.played += 1
        s_home.gf += home_g
        s_home.ga += away_g
        s_away.gf += away_g
        s_away.ga += home_g

        if home_g > away_g:
            s_home.wins += 1
            s_home.points += 3
            s_away.losses += 1
        elif home_g < away_g:
            s_away.wins += 1
            s_away.points += 3
            s_home.losses += 1
        else:
            s_home.draws += 1
            s_home.points += 1
            s_away.draws += 1
            s_away.points += 1

    return _sort_standings(list(standings.values()))


def _sort_standings(standings: list[TeamStanding]) -> list[TeamStanding]:
    """Ordena la tabla por los criterios de desempate deterministas (R4).

    Criterios (en orden):
    1. Puntos (descendente).
    2. Diferencia de goles GF−GA (descendente).
    3. Goles a favor GF (descendente).
    4. Fuerza de ataque del modelo (descendente) — o código FIFA (ascendente) si no hay.

    Args:
        standings: List of TeamStanding objects to sort.

    Returns:
        Sorted list with best team first.
    """
    return sorted(
        standings,
        key=lambda s: (
            -s.points,
            -s.gd,
            -s.gf,
            -s.attack_strength,
            s.team,  # desempate final: alfabético ascendente (determinista)
        ),
    )


# ---------------------------------------------------------------------------
# Ranking de terceros (R4)
# ---------------------------------------------------------------------------

def rank_third_places(
    group_thirds: dict[str, TeamStanding],
) -> list[TeamStanding]:
    """Clasifica los 12 terceros de grupo para seleccionar los 8 mejores (R4).

    Usa los mismos criterios de desempate que la tabla de grupo.
    Los primeros 8 en el ranking avanzan a R32.

    SIMPLIFICACIÓN DOCUMENTADA: El reglamento FIFA 2026 para el ranking de
    terceros puede incluir criterios adicionales (puntos obtenidos vs los
    primeros dos de cada grupo, etc.). Esta implementación usa el ranking
    simple por los mismos criterios de la tabla de grupo.

    Args:
        group_thirds: Dict mapping group label to the TeamStanding of that group's
            third-place finisher.

    Returns:
        List of all 12 third-place standings sorted best → worst.
    """
    thirds = list(group_thirds.values())
    return _sort_standings(thirds)


def get_group_qualified(
    table: list[TeamStanding],
) -> tuple[TeamStanding, TeamStanding, TeamStanding, TeamStanding]:
    """Retorna los 4 clasificados de un grupo en orden (1°, 2°, 3°, 4°) (R4).

    Args:
        table: Sorted list of 4 TeamStanding objects (best first).

    Returns:
        Tuple of (first, second, third, fourth) TeamStanding objects.
    """
    if len(table) != 4:
        raise ValueError(f"La tabla del grupo debe tener exactamente 4 equipos, tiene {len(table)}.")
    return table[0], table[1], table[2], table[3]
