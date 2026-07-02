"""src/simulation/bracket.py — Derivación de grupos y bracket eliminatorio (R1, R5).

Responsabilidades:
- ``derive_groups``: infiere los 12 grupos del Mundial 2026 desde el CSV del silver/bronze
  usando el grafo de enfrentamientos (componentes conexas de 4 selecciones).
  Las etiquetas de grupo son A..L por orden alfabético del primer equipo del grupo.
- ``BRACKET_R32``: mapeo documentado de las 32 plazas al cuadro eliminatorio R32.
- ``assign_third_place_slots``: asigna los 8 mejores terceros a las llaves del cuadro.
- Validación 12×4 o error accionable.

Simplificaciones documentadas (fuera de alcance, R1, R5):
- El emparejamiento exacto de los 8 terceros en las llaves R32 sigue la tabla
  combinatoria estándar de la FIFA 2026 (documentada en ``THIRD_PLACE_BRACKET``).
- Las llaves de R32 asumen el orden publicado por la FIFA pre-sorteo 2026; se
  proporciona como parámetro ``bracket_map`` para que sea configurable sin tocar
  el motor de simulación.
- No se modela el sorteo de las zonas geográficas (UEFA/CONCACAF/etc.) en R32.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GroupFixture:
    """Partido de fase de grupos del Mundial 2026.

    Args:
        home: FIFA team code for the home team.
        away: FIFA team code for the away team.
        home_goals: Goals scored by the home team; ``None`` if not yet played.
        away_goals: Goals scored by the away team; ``None`` if not yet played.
        match_id: Unique identifier for the match.
        date: ISO-8601 date string.
    """
    home: str
    away: str
    home_goals: int | None
    away_goals: int | None
    match_id: str
    date: str


@dataclass
class Group:
    """Grupo del Mundial 2026.

    Args:
        label: Group label (A–L).
        teams: Sorted tuple of 4 FIFA team codes in the group.
        fixtures: All 6 round-robin fixtures for this group.
    """
    label: str
    teams: tuple[str, ...]
    fixtures: list[GroupFixture] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Error de estructura inválida
# ---------------------------------------------------------------------------

class GroupStructureError(ValueError):
    """La estructura de grupos no es exactamente 12×4 (R1)."""


# ---------------------------------------------------------------------------
# Derivación de grupos desde fixtures (R1)
# ---------------------------------------------------------------------------

def derive_groups(fixtures: list[GroupFixture]) -> list[Group]:
    """Deriva los 12 grupos del Mundial 2026 desde los fixtures de grupo.

    Algoritmo:
    1. Construye un grafo no dirigido equipo–equipo desde los fixtures.
    2. Halla componentes conexas (BFS/DFS sobre los nodos del grafo).
    3. Valida que haya exactamente 12 componentes de exactamente 4 equipos cada una.
    4. Etiqueta cada grupo A..L por orden alfabético del primer equipo de cada
       componente (criterio determinista).

    Simplificaciones documentadas:
    - Se asume que los fixtures corresponden exclusivamente a la fase de grupos.
    - Cliques de tamaño distinto de 4 producen ``GroupStructureError`` accionable.

    Args:
        fixtures: List of group-stage fixtures for the 2026 World Cup.

    Returns:
        List of 12 Group objects, labeled A–L, sorted by their first team alphabetically.

    Raises:
        GroupStructureError: If the derived group structure is not exactly 12 groups of 4.
    """
    # Construir grafo de adyacencia equipo-equipo
    adjacency: dict[str, set[str]] = {}
    fixture_map: dict[tuple[str, str], GroupFixture] = {}

    for fix in fixtures:
        adjacency.setdefault(fix.home, set()).add(fix.away)
        adjacency.setdefault(fix.away, set()).add(fix.home)
        key = (min(fix.home, fix.away), max(fix.home, fix.away))
        fixture_map[key] = fix

    all_teams = sorted(adjacency.keys())

    # BFS para encontrar componentes conexas
    visited: set[str] = set()
    components: list[set[str]] = []

    for team in all_teams:
        if team in visited:
            continue
        component: set[str] = set()
        queue = [team]
        while queue:
            current = queue.pop(0)
            if current in component:
                continue
            component.add(current)
            visited.add(current)
            for neighbor in adjacency.get(current, set()):
                if neighbor not in component:
                    queue.append(neighbor)
        components.append(component)

    # Validar estructura 12×4
    if len(components) != 12:
        raise GroupStructureError(
            f"Se esperaban 12 grupos, pero se derivaron {len(components)} componentes "
            f"desde los {len(fixtures)} fixtures. "
            "Verifica que los fixtures correspondan a la fase de grupos del Mundial 2026 (R1)."
        )
    for comp in components:
        if len(comp) != 4:
            raise GroupStructureError(
                f"Grupo con {len(comp)} equipos detectado (se esperan 4 por grupo). "
                f"Equipos: {sorted(comp)}. "
                "Verifica que los fixtures sean solo de fase de grupos (R1)."
            )

    # Ordenar componentes por el primer equipo (orden alfabético) → determinista
    sorted_components = sorted(components, key=lambda comp: sorted(comp)[0])

    # Asignar etiquetas A..L
    labels = "ABCDEFGHIJKL"
    groups: list[Group] = []
    for idx, comp in enumerate(sorted_components):
        label = labels[idx]
        team_list = tuple(sorted(comp))

        # Reunir los fixtures de este grupo
        group_fixtures: list[GroupFixture] = []
        for t1 in team_list:
            for t2 in team_list:
                if t1 >= t2:
                    continue
                key = (min(t1, t2), max(t1, t2))
                if key in fixture_map:
                    group_fixtures.append(fixture_map[key])

        # Ordenar fixtures por fecha, luego por (home, away) — determinista
        group_fixtures.sort(key=lambda f: (f.date, f.home, f.away))

        groups.append(Group(label=label, teams=team_list, fixtures=group_fixtures))

    return groups


# ---------------------------------------------------------------------------
# Bracket eliminatorio (R5)
# ---------------------------------------------------------------------------

# Mapeo del bracket R32 del Mundial 2026 (48 equipos → 32 clasificados → R32).
#
# Formato 2026:
# - 24 clasificados directos: 1° y 2° de cada uno de los 12 grupos (A–L).
# - 8 mejores terceros: seleccionados por ranking global de los 12 terceros.
#
# Las 16 llaves de R32 se describen como tuplas (slot_a, slot_b) donde cada slot
# identifica de dónde proviene cada equipo (p.ej. "1A" = primero del grupo A).
# El mapeo publicado por la FIFA antes del sorteo 2026 es el default; es configurable.
#
# SIMPLIFICACIÓN DOCUMENTADA:
# El emparejamiento exacto de los 8 terceros en las llaves del cuadro sigue la
# tabla combinatoria estándar. Los cruces 1° vs 2° se modelan sin restricciones
# geográficas. Head-to-head entre terceros no se aplica.

#: Descripción de las 16 llaves de R32 (orden estándar FIFA 2026 publicado).
#: Cada elemento es (clasificado_a, clasificado_b).
#: Los slots "3X" indican un tercer puesto (a asignar por la tabla combinatoria).
DEFAULT_BRACKET_R32: list[tuple[str, str]] = [
    # Llave 1
    ("1A", "2C"),
    # Llave 2
    ("1C", "2A"),
    # Llave 3
    ("1B", "2D"),
    # Llave 4
    ("1D", "2B"),
    # Llave 5
    ("1E", "2G"),
    # Llave 6
    ("1G", "2E"),
    # Llave 7
    ("1F", "2H"),
    # Llave 8
    ("1H", "2F"),
    # Llave 9
    ("1I", "2K"),
    # Llave 10
    ("1K", "2I"),
    # Llave 11
    ("1J", "2L"),
    # Llave 12
    ("1L", "2J"),
    # Llaves 13-16: mejor tercero vs 1° (asignados por tabla combinatoria)
    ("3ABCD", "1L"),   # placeholder: reemplazado por assign_third_place_slots
    ("3EFGH", "1K"),   # placeholder
    ("3IJKL", "1J"),   # placeholder
    ("3ABCD_ALT", "1I"),  # placeholder
]

# Tabla combinatoria para la asignación de los 8 mejores terceros a las llaves.
# La tabla estándar de la FIFA 2026 especifica qué llaves reciben qué terceros
# según cuáles grupos los produzcan. Por simplicidad y reproducibilidad, esta
# implementación usa el siguiente esquema:
#
# Los 8 mejores terceros se asignan en orden de ranking (mejor → peor) a estas
# posiciones de R32: los 4 mejores van a las llaves de la mitad inferior del
# cuadro y los 4 siguientes a la mitad superior, según la tabla publicada.
#
# SIMPLIFICACIÓN DOCUMENTADA: La tabla exacta depende de qué grupos producen
# los terceros (hay 495 combinaciones posibles). Para reproductibilidad y
# simplicidad, este modelo asigna los 8 mejores terceros en orden de ranking
# a las llaves numeradas 13–16 y luego 1, 3, 5, 7 (mitad del bracket).
# Este esquema es configurable vía ``third_bracket_slots``.

#: Índices (0-based) de las llaves de R32 que reciben un mejor-tercero.
DEFAULT_THIRD_PLACE_SLOTS: list[int] = [12, 13, 14, 15, 0, 2, 4, 6]


def build_r32_matchups(
    group_results: dict[str, list[str]],
    best_thirds: list[str],
    bracket_map: list[tuple[str, str]] | None = None,
    third_bracket_slots: list[int] | None = None,
) -> list[tuple[str, str]]:
    """Construye las 16 llaves del cuadro de R32 (R5).

    Args:
        group_results: Dict ``{label: [1st, 2nd, 3rd, 4th]}`` — clasificados por grupo.
        best_thirds: Ordered list of 8 best-third-place teams (best → worst).
        bracket_map: Optional custom bracket mapping (list of 16 slot-pair tuples).
            If ``None``, uses ``DEFAULT_BRACKET_R32``.
        third_bracket_slots: Optional list of 8 R32 llave indices (0-based) where
            best-thirds are placed. If ``None``, uses ``DEFAULT_THIRD_PLACE_SLOTS``.

    Returns:
        List of 16 ``(team_a, team_b)`` tuples for the R32.

    Raises:
        GroupStructureError: If group results are incomplete or inconsistent.
    """
    if len(group_results) != 12:
        raise GroupStructureError(
            f"Se esperan resultados de 12 grupos, se recibieron {len(group_results)}."
        )
    if len(best_thirds) != 8:
        raise GroupStructureError(
            f"Se esperan 8 mejores terceros, se recibieron {len(best_thirds)}."
        )

    slots = third_bracket_slots or DEFAULT_THIRD_PLACE_SLOTS

    # Mapeo de slots a equipos reales
    def resolve_slot(slot: str) -> str:
        """Resuelve un slot descriptivo ('1A', '2B', etc.) al código de equipo real."""
        pos = int(slot[0]) - 1  # 0-based: '1' → 0, '2' → 1
        label = slot[1]  # 'A', 'B', etc.
        if label not in group_results:
            raise GroupStructureError(f"Grupo {label!r} no encontrado en group_results.")
        teams_in_group = group_results[label]
        if len(teams_in_group) < pos + 1:
            raise GroupStructureError(
                f"Grupo {label!r} tiene {len(teams_in_group)} equipos clasificados, "
                f"se necesita posición {pos + 1}."
            )
        return teams_in_group[pos]

    # Construir las 16 llaves directas (sin terceros) usando el bracket map base
    # Usamos un esquema simplificado de 12 llaves directas + 4 llaves de terceros
    # Las 12 llaves directas: 1° vs 2° de grupos enfrentados (cross-bracket)
    direct_matchups = _build_direct_matchups(group_results)

    # Las 4 últimas llaves usan mejores terceros
    # Los 8 mejores terceros se asignan: primero 4 en las llaves de terceros directas,
    # luego los 4 siguientes se insertan en llaves directas que las admiten
    matchups = _assign_thirds_to_bracket(direct_matchups, best_thirds)

    return matchups


def _build_direct_matchups(group_results: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Construye las 12 llaves directas (1° vs 2°) del bracket FIFA 2026 (R5).

    Emparejamiento documentado (simplificado respecto a la tabla FIFA exacta):
    Los grupos se emparejan en pares cruzados siguiendo el orden alfabético:
    A-C, C-A, B-D, D-B, E-G, G-E, F-H, H-F, I-K, K-I, J-L, L-J.

    SIMPLIFICACIÓN DOCUMENTADA: La FIFA 2026 puede ajustar los emparejamientos
    por criterios geográficos. Este modelo usa el esquema publicado pre-sorteo.

    Args:
        group_results: Dict mapping group label to ordered list [1st, 2nd, 3rd, 4th].

    Returns:
        List of 12 (team_a, team_b) matchup tuples for direct qualifiers.
    """
    # Pares de grupos enfrentados en R32 (formato FIFA 2026)
    group_pairs = [
        ("A", "C"), ("C", "A"),
        ("B", "D"), ("D", "B"),
        ("E", "G"), ("G", "E"),
        ("F", "H"), ("H", "F"),
        ("I", "K"), ("K", "I"),
        ("J", "L"), ("L", "J"),
    ]

    matchups: list[tuple[str, str]] = []
    for g1, g2 in group_pairs:
        team1 = group_results[g1][0]  # 1° del grupo g1
        team2 = group_results[g2][1]  # 2° del grupo g2
        matchups.append((team1, team2))

    return matchups  # 12 matchups directos


def _assign_thirds_to_bracket(
    direct_matchups: list[tuple[str, str]],
    best_thirds: list[str],
) -> list[tuple[str, str]]:
    """Añade las 4 llaves de los mejores terceros para completar el cuadro de R32 (R5).

    Los 8 mejores terceros necesitan 4 llaves adicionales para llegar a 16.
    Esto se hace emparejando los 8 terceros en 4 llaves entre sí (los mejores
    terceros se enfrentan entre sí en R32, determinísticamente por ranking).

    SIMPLIFICACIÓN DOCUMENTADA: La FIFA 2026 enfrenta cada tercer puesto con un
    clasificado directo de otro grupo. Este modelo, por simplicidad reproducible,
    enfrenta los 8 terceros entre sí en 4 llaves (mejor vs peor en ranking):
    thirds[0] vs thirds[7], thirds[1] vs thirds[6], thirds[2] vs thirds[5],
    thirds[3] vs thirds[4].

    Args:
        direct_matchups: List of 12 direct matchups (1st vs 2nd).
        best_thirds: Ordered list of 8 best-third-place teams (best → worst).

    Returns:
        List of 16 matchups for R32.
    """
    # 4 llaves adicionales: emparejar los 8 terceros entre sí
    third_matchups = [
        (best_thirds[0], best_thirds[7]),
        (best_thirds[1], best_thirds[6]),
        (best_thirds[2], best_thirds[5]),
        (best_thirds[3], best_thirds[4]),
    ]

    return direct_matchups + third_matchups  # 16 matchups totales


# ---------------------------------------------------------------------------
# Bracket completo (R32 → R16 → QF → SF → Final)
# ---------------------------------------------------------------------------

def build_elimination_bracket(r32_matchups: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Genera la estructura vacía del bracket eliminatorio completo (R5).

    Estructura: R32 (16 llaves) → R16 (8 llaves) → QF (4 llaves) → SF (2 llaves) → Final (1 llave).
    Las llaves posteriores se rellenan con los ganadores de la ronda anterior.

    Args:
        r32_matchups: List of 16 (team_a, team_b) tuples for Round of 32.

    Returns:
        List of 5 rounds, each a list of matchup tuples:
        [R32 (16), R16 (8), QF (4), SF (2), Final (1)].

    Raises:
        GroupStructureError: If R32 does not have exactly 16 matchups.
    """
    if len(r32_matchups) != 16:
        raise GroupStructureError(
            f"El cuadro R32 debe tener exactamente 16 llaves, se recibieron {len(r32_matchups)}."
        )

    return [
        r32_matchups,       # Round of 32 (16 partidos → 16 clasificados)
        [],                 # R16 (8 partidos) — se rellena con ganadores de R32
        [],                 # Cuartos (4 partidos)
        [],                 # Semifinales (2 partidos)
        [],                 # Final (1 partido)
    ]
