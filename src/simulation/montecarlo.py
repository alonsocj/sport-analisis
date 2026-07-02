"""src/simulation/montecarlo.py — Simulación Monte Carlo del Mundial 2026 (R2, R3, R6, R9, R10).

Responsabilidades:
- ``load_wc2026_fixtures``: carga los 72 fixtures de grupo desde el silver/bronze.
- ``precompute_match_params``: precomputa λ_home y λ_away + matrices DC para cada
  fixture pendiente UNA SOLA VEZ (R10).
- ``sample_score``: muestrea un marcador desde la distribución DC del partido (R3).
- ``simulate_match``: devuelve (home_g, away_g) — real si jugado, muestreado si no (R2).
- ``simulate_elimination_match``: simula un partido eliminatorio; empate resuelto
  por Bernoulli ponderada por la probabilidad de victoria del modelo (R5).
- ``run_simulation``: ejecuta N simulaciones; agrega P(avanzar de grupo), P(R16),
  P(Cuartos), P(Semis), P(Final), P(título) + error MC estándar (R6).
- Determinismo: ``numpy.random.default_rng(seed)`` con seed inyectada (R3).
- Sin red; sin reloj; sin dependencias nuevas (numpy basta para el RNG).

Muestreo de empate en eliminatoria (R5) — método documentado:
CUANDO el marcador muestreado es empate en la fase eliminatoria, el ganador se
determina por una Bernoulli ponderada: P(home_wins | draw) proporcional a
``prob_home / (prob_home + prob_away)`` del modelo, donde ``prob_home`` y
``prob_away`` son las probabilidades 1X2 de la matriz Dixon-Coles. Este método
modela la "prórroga/penales" como una extensión de la distribución de fuerzas.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..models.dixon_coles import (
    DixonColesParams,
    load_params,
    match_rates,
    score_matrix,
)
from ..ingestion.teams import is_host
from .bracket import (
    GroupFixture,
    Group,
    GroupStructureError,
    derive_groups,
    build_r32_matchups,
    _build_direct_matchups,
    _assign_thirds_to_bracket,
)
from .standings import (
    TeamStanding,
    compute_group_table,
    get_group_qualified,
    rank_third_places,
)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

WC_TOURNAMENT = "FIFA World Cup"
DEFAULT_SILVER_PATH = Path("data/silver/matches.csv")
DEFAULT_BRONZE_PATH = Path("data/bronze/public_results/results.csv")
DEFAULT_N_SIMULATIONS = 10_000
MIN_N_SIMULATIONS = 1_000
DEFAULT_SEED = 42
MAX_GOALS = 10  # soporte de la matriz de marcadores

# Rondas del torneo (para indexar contadores)
ROUNDS = ("group", "r32", "r16", "qf", "sf", "final", "champion")

# Nombre de la columna FIFA en el silver
SILVER_TOURNAMENT_COL = "tournament"
SILVER_HOME_COL = "home_code"
SILVER_AWAY_COL = "away_code"
SILVER_HOME_GOALS_COL = "home_goals"
SILVER_AWAY_GOALS_COL = "away_goals"
SILVER_MATCH_ID_COL = "match_id"
SILVER_DATE_COL = "date"


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------

@dataclass
class MatchParams:
    """Parámetros precomputados para un partido pendiente (R10).

    Args:
        home: FIFA code of the home team.
        away: FIFA code of the away team.
        lambda_home: Expected goals for the home team.
        lambda_away: Expected goals for the away team.
        matrix: Score probability matrix M[home_goals, away_goals] from Dixon-Coles.
        prob_home: Probability of home win (P(X > Y)).
        prob_away: Probability of away win (P(X < Y)).
    """
    home: str
    away: str
    lambda_home: float
    lambda_away: float
    matrix: np.ndarray
    prob_home: float
    prob_away: float


@dataclass
class SimulationResult:
    """Resultado agregado de las N simulaciones Monte Carlo (R6).

    Args:
        n_simulations: Number of simulations run.
        probabilities: Dict mapping team code to dict of round probabilities.
        std_errors: Dict mapping team code to dict of Monte Carlo standard errors.
    """
    n_simulations: int
    probabilities: dict[str, dict[str, float]]
    std_errors: dict[str, dict[str, float]]


# ---------------------------------------------------------------------------
# Carga de fixtures del Mundial 2026
# ---------------------------------------------------------------------------

def load_wc2026_fixtures(
    silver_path: Path | str = DEFAULT_SILVER_PATH,
    as_of: str | None = None,
) -> list[GroupFixture]:
    """Carga los 72 fixtures de grupo del Mundial 2026 desde el silver (R2).

    Los partidos con marcador real (jornada ya jugada) incluyen ``home_goals``
    y ``away_goals`` como enteros. Los partidos pendientes tienen ``None``.

    El silver contiene los partidos ya jugados; para obtener los pendientes con
    sus metadatos (fecha, match_id), se necesita el bronze. Sin embargo, el
    silver tiene los 72 fixtures del torneo (incluyendo los pendientes como NA).

    NOTA: Si el silver no tiene los partidos pendientes (NA), se cargan desde
    el bronze con ``home_goals = away_goals = None``.

    Args:
        silver_path: Path to the silver matches CSV.
        as_of: Optional ISO date; if provided, only played matches up to this
            date are treated as played (for anti-leakage in backtesting).

    Returns:
        List of 72 GroupFixture objects for the 2026 World Cup group stage.

    Raises:
        FileNotFoundError: If neither silver nor bronze has WC 2026 fixtures.
        ValueError: If group structure cannot be derived from the fixtures.
    """
    silver_path = Path(silver_path)

    fixtures: list[GroupFixture] = []

    # Cargar los partidos jugados desde el silver
    if silver_path.is_file():
        with silver_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if row.get(SILVER_TOURNAMENT_COL) != WC_TOURNAMENT:
                    continue
                if row.get("date", "") < "2026-01-01":
                    continue  # solo Mundial 2026, no histórico

                match_date = row.get(SILVER_DATE_COL, "")

                # Anti-leakage: si as_of está presente, los partidos posteriores
                # se tratan como pendientes
                is_played = True
                if as_of is not None and match_date > as_of:
                    is_played = False

                try:
                    home_g: int | None = int(row[SILVER_HOME_GOALS_COL]) if is_played else None
                    away_g: int | None = int(row[SILVER_AWAY_GOALS_COL]) if is_played else None
                except (ValueError, TypeError, KeyError):
                    home_g = None
                    away_g = None

                fix = GroupFixture(
                    home=row[SILVER_HOME_COL],
                    away=row[SILVER_AWAY_COL],
                    home_goals=home_g,
                    away_goals=away_g,
                    match_id=row.get(SILVER_MATCH_ID_COL, ""),
                    date=match_date,
                )
                fixtures.append(fix)

    # Si el silver no tiene todos los fixtures, complementar con el bronze
    silver_pairs = {(f.home, f.away) for f in fixtures}
    bronze_path = DEFAULT_BRONZE_PATH

    if bronze_path.is_file():
        with bronze_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if row.get("tournament") != WC_TOURNAMENT:
                    continue
                if row.get("date", "") < "2026-01-01":
                    continue

                # Mapear nombres del bronze a códigos FIFA
                home_name = row.get("home_team", "")
                away_name = row.get("away_team", "")

                from ..ingestion.public_data import to_fifa_code
                home_code = to_fifa_code(home_name)
                away_code = to_fifa_code(away_name)

                if not home_code or not away_code:
                    continue

                if (home_code, away_code) in silver_pairs:
                    continue  # ya cargado desde el silver

                # Partido pendiente del bronze
                home_score_raw = row.get("home_score", "NA")
                away_score_raw = row.get("away_score", "NA")

                try:
                    home_g = int(home_score_raw)
                    away_g = int(away_score_raw)
                    # Anti-leakage por as_of
                    match_date = row.get("date", "")
                    if as_of is not None and match_date > as_of:
                        home_g = None
                        away_g = None
                except (ValueError, TypeError):
                    home_g = None
                    away_g = None

                match_date = row.get("date", "")
                fix = GroupFixture(
                    home=home_code,
                    away=away_code,
                    home_goals=home_g,
                    away_goals=away_g,
                    match_id=f"{home_code}_{away_code}_{match_date}",
                    date=match_date,
                )
                fixtures.append(fix)

    if not fixtures:
        raise FileNotFoundError(
            f"No se encontraron fixtures del Mundial 2026 en {silver_path} "
            f"ni en {bronze_path}."
        )

    return fixtures


# ---------------------------------------------------------------------------
# Precomputo de parámetros (R10)
# ---------------------------------------------------------------------------

def precompute_match_params(
    fixtures: list[GroupFixture],
    params: DixonColesParams,
    roster_multipliers: dict[str, float] | None = None,
    form_factor: Callable[[str, str], tuple[float, float]] | None = None,
) -> dict[tuple[str, str], MatchParams]:
    """Precomputa λ y matrices DC para todos los partidos pendientes UNA SOLA VEZ (R10).

    Los partidos ya jugados (marcador real) no necesitan precomputo de λ.
    Los pendientes calculan ``lambda_home``, ``lambda_away`` y la matriz de
    probabilidades de marcadores Dixon-Coles, incluyendo la corrección τ.

    Si ``roster_multipliers`` está presente, aplica el multiplicador de ataque
    a ``lambda_home`` y ``lambda_away`` ANTES de computar la matriz (R9).

    Si ``form_factor`` está presente (Feature 16, R4), aplica el factor de forma
    sobre las λ DESPUÉS del roster: ``λ' = λ_DC · exp(γ·f_team)``. Con ``None``
    o γ=0 → comportamiento v1 idéntico (no-regresión).

    Args:
        fixtures: All group-stage fixtures (played and pending).
        params: Trained Dixon-Coles model parameters.
        roster_multipliers: Optional dict mapping team code to attack multiplier.
            Applied to lambda before form factor. ``None`` → no multiplier.
        form_factor: Optional callable ``(home, away) → (mult_home, mult_away)``
            (Feature 16). ``None`` → v1 behaviour exact.

    Returns:
        Dict mapping ``(home_code, away_code)`` to ``MatchParams``.
        Only includes pending fixtures (those with ``None`` scores).
    """
    precomputed: dict[tuple[str, str], MatchParams] = {}

    for fix in fixtures:
        if fix.home_goals is not None and fix.away_goals is not None:
            continue  # ya jugado: no precomputar

        home = fix.home
        away = fix.away

        # Verificar que ambos equipos estén en los parámetros
        if home not in params.attack or away not in params.attack:
            # Usar lambda de fallback (1.0) para equipos fuera del modelo
            lambda_h = 1.0
            lambda_a = 1.0
        else:
            h = 1.0 if is_host(home) else 0.0
            lambda_h, lambda_a = match_rates(
                params.mu,
                params.home_advantage,
                params.attack[home],
                params.defense[home],
                params.attack[away],
                params.defense[away],
                h,
            )
            lambda_h = float(lambda_h)
            lambda_a = float(lambda_a)

        # Aplicar multiplicador de roster (R9)
        if roster_multipliers:
            lambda_h *= roster_multipliers.get(home, 1.0)
            lambda_a *= roster_multipliers.get(away, 1.0)

        # Feature 16: factor de forma (R4) — DESPUÉS del roster
        if form_factor is not None:
            mult_h, mult_a = form_factor(home, away)
            lambda_h *= mult_h
            lambda_a *= mult_a

        # Precomputar la matriz DC (score_matrix incluye corrección tau)
        mat = score_matrix(lambda_h, lambda_a, params.rho, MAX_GOALS)

        # Probabilidades 1X2 desde la matriz
        prob_home = float(np.tril(mat, -1).sum())  # X > Y
        prob_away = float(np.triu(mat, 1).sum())    # X < Y

        precomputed[(home, away)] = MatchParams(
            home=home,
            away=away,
            lambda_home=lambda_h,
            lambda_away=lambda_a,
            matrix=mat,
            prob_home=prob_home,
            prob_away=prob_away,
        )

    return precomputed


# ---------------------------------------------------------------------------
# Muestreo de marcadores (R3)
# ---------------------------------------------------------------------------

def sample_score(
    match_params: MatchParams,
    rng: np.random.Generator,
) -> tuple[int, int]:
    """Muestrea un marcador desde la distribución Dixon-Coles del partido (R3).

    Muestrea la posición (i, j) de la matriz de probabilidades usando
    ``rng.choice`` sobre los índices aplanados, con las probabilidades como pesos.
    Esto garantiza reproducibilidad byte a byte dado el mismo RNG (R3).

    Args:
        match_params: Precomputed match parameters including the score matrix.
        rng: Numpy random Generator with injected seed.

    Returns:
        Tuple (home_goals, away_goals).
    """
    mat = match_params.matrix
    n = mat.shape[0]

    # Aplanar la matriz y muestrear un índice
    flat_probs = mat.flatten()
    flat_probs = flat_probs / flat_probs.sum()  # renormalizar por precisión numérica
    idx = rng.choice(len(flat_probs), p=flat_probs)

    home_goals = idx // n
    away_goals = idx % n
    return int(home_goals), int(away_goals)


def simulate_match(
    fix: GroupFixture,
    precomputed: dict[tuple[str, str], MatchParams],
    rng: np.random.Generator,
) -> tuple[int, int]:
    """Devuelve (home_goals, away_goals): real si jugado, muestreado si pendiente (R2).

    Args:
        fix: GroupFixture with or without real scores.
        precomputed: Precomputed match parameters for pending fixtures.
        rng: Numpy random Generator.

    Returns:
        Tuple (home_goals, away_goals).
    """
    if fix.home_goals is not None and fix.away_goals is not None:
        return int(fix.home_goals), int(fix.away_goals)

    key = (fix.home, fix.away)
    if key in precomputed:
        return sample_score(precomputed[key], rng)

    # Fallback: Poisson independiente con lambda=1 si no hay parámetros
    return int(rng.poisson(1.2)), int(rng.poisson(1.0))


def simulate_elimination_match(
    home: str,
    away: str,
    precomputed_elim: dict[tuple[str, str], MatchParams],
    rng: np.random.Generator,
    params: DixonColesParams,
    roster_multipliers: dict[str, float] | None = None,
    form_factor: Callable[[str, str], tuple[float, float]] | None = None,
) -> str:
    """Simula un partido eliminatorio y devuelve el ganador (R5).

    El partido se simula muestreando de la distribución DC. Si el resultado
    es empate, se resuelve por Bernoulli ponderada por la fuerza del modelo:
    P(home_wins | draw) = prob_home / (prob_home + prob_away).

    MÉTODO DOCUMENTADO (R5):
    La prórroga/penales se modela como una Bernoulli cuya probabilidad de
    victoria del local es proporcional a su probabilidad de victoria en 90'
    relativa a la suma de las probabilidades de victoria de ambos equipos.
    Esto preserva la relación de fuerzas del modelo sin requerir un modelo
    específico de penales.

    Args:
        home: FIFA code of the home team.
        away: FIFA code of the away team.
        precomputed_elim: Precomputed match parameters for elimination matches.
        rng: Numpy random Generator.
        params: Dixon-Coles model parameters (for on-demand computation if needed).
        roster_multipliers: Optional attack multipliers to apply.

    Returns:
        FIFA code of the winner.
    """
    key = (home, away)

    # Obtener o computar los parámetros del partido
    if key not in precomputed_elim:
        # Computar al vuelo para cruces eliminatorios nuevos
        match_param = _compute_single_match_params(
            home, away, params, roster_multipliers, form_factor
        )
        precomputed_elim[key] = match_param
    else:
        match_param = precomputed_elim[key]

    home_g, away_g = sample_score(match_param, rng)

    if home_g > away_g:
        return home
    elif away_g > home_g:
        return away
    else:
        # Empate: resolver por Bernoulli ponderada por fuerza del modelo
        p_home = match_param.prob_home
        p_away = match_param.prob_away
        total = p_home + p_away
        if total <= 0:
            # Equipos con misma fuerza: 50/50
            p_home_win = 0.5
        else:
            p_home_win = p_home / total

        if rng.random() < p_home_win:
            return home
        else:
            return away


def _compute_single_match_params(
    home: str,
    away: str,
    params: DixonColesParams,
    roster_multipliers: dict[str, float] | None = None,
    form_factor: Callable[[str, str], tuple[float, float]] | None = None,
) -> MatchParams:
    """Computa MatchParams para un cruce eliminatorio específico.

    Args:
        home: FIFA code of the home team.
        away: FIFA code of the away team.
        params: Dixon-Coles model parameters.
        roster_multipliers: Optional attack multipliers.

    Returns:
        MatchParams for the matchup.
    """
    if home not in params.attack or away not in params.attack:
        lambda_h = 1.0
        lambda_a = 1.0
    else:
        h = 1.0 if is_host(home) else 0.0
        lambda_h, lambda_a = match_rates(
            params.mu,
            params.home_advantage,
            params.attack[home],
            params.defense[home],
            params.attack[away],
            params.defense[away],
            h,
        )
        lambda_h = float(lambda_h)
        lambda_a = float(lambda_a)

    if roster_multipliers:
        lambda_h *= roster_multipliers.get(home, 1.0)
        lambda_a *= roster_multipliers.get(away, 1.0)

    # Feature 16: factor de forma (R4) — DESPUÉS del roster
    if form_factor is not None:
        mult_h, mult_a = form_factor(home, away)
        lambda_h *= mult_h
        lambda_a *= mult_a

    mat = score_matrix(lambda_h, lambda_a, params.rho, MAX_GOALS)
    prob_home = float(np.tril(mat, -1).sum())
    prob_away = float(np.triu(mat, 1).sum())

    return MatchParams(
        home=home,
        away=away,
        lambda_home=lambda_h,
        lambda_away=lambda_a,
        matrix=mat,
        prob_home=prob_home,
        prob_away=prob_away,
    )


# ---------------------------------------------------------------------------
# Simulación de una iteración completa
# ---------------------------------------------------------------------------

def _simulate_one(
    groups: list[Group],
    precomputed: dict[tuple[str, str], MatchParams],
    params: DixonColesParams,
    rng: np.random.Generator,
    roster_multipliers: dict[str, float] | None,
    form_factor: Callable[[str, str], tuple[float, float]] | None = None,
) -> dict[str, str]:
    """Ejecuta una simulación completa del torneo y devuelve la ronda alcanzada por cada equipo.

    Args:
        groups: List of 12 Group objects.
        precomputed: Precomputed match parameters for pending group fixtures.
        params: Dixon-Coles model parameters.
        rng: Numpy random Generator.
        roster_multipliers: Optional attack multipliers.

    Returns:
        Dict mapping team code to the furthest round reached:
        'group', 'r32', 'r16', 'qf', 'sf', 'final', 'champion'.
    """
    # Resultado de cada equipo: ronda máxima alcanzada
    results: dict[str, str] = {}
    for grp in groups:
        for t in grp.teams:
            results[t] = "group"  # todos empiezan en fase de grupos

    # --- Fase de grupos ---
    attack_strength = params.attack if hasattr(params, "attack") else {}

    group_results: dict[str, list[str]] = {}  # label → [1°, 2°, 3°, 4°]
    group_thirds: dict[str, "TeamStanding"] = {}  # label → 3° TeamStanding

    for grp in groups:
        # Simular todos los fixtures del grupo
        sim_fixtures: list[GroupFixture] = []
        for fix in grp.fixtures:
            if fix.home_goals is not None and fix.away_goals is not None:
                sim_fixtures.append(fix)
            else:
                home_g, away_g = simulate_match(fix, precomputed, rng)
                sim_fixtures.append(GroupFixture(
                    home=fix.home,
                    away=fix.away,
                    home_goals=home_g,
                    away_goals=away_g,
                    match_id=fix.match_id,
                    date=fix.date,
                ))

        # Calcular tabla
        table = compute_group_table(
            grp.teams,
            sim_fixtures,
            attack_strength=dict(attack_strength) if attack_strength else None,
        )

        first, second, third, fourth = get_group_qualified(table)
        group_results[grp.label] = [first.team, second.team, third.team, fourth.team]
        group_thirds[grp.label] = third

        # El 4° queda eliminado en grupos (ya en 'group', que es el default)

    # Ranking de terceros → top 8
    all_thirds_ranked = rank_third_places(group_thirds)
    best_thirds_teams = [s.team for s in all_thirds_ranked[:8]]

    # Marcar los equipos que pasan de grupos
    for label, positions in group_results.items():
        results[positions[0]] = "r32"  # 1°
        results[positions[1]] = "r32"  # 2°
    for team in best_thirds_teams:
        results[team] = "r32"  # mejor tercero

    # --- Bracket eliminatorio R32 → Final ---
    precomputed_elim: dict[tuple[str, str], MatchParams] = {}

    # Construir las 16 llaves de R32
    direct = _build_direct_matchups(group_results)
    r32_matchups = _assign_thirds_to_bracket(direct, best_thirds_teams)

    # Rondas eliminatorias
    round_labels = ["r16", "qf", "sf", "final", "champion"]
    current_matchups = r32_matchups

    for round_idx, advance_label in enumerate(round_labels):
        winners: list[str] = []
        for home, away in current_matchups:
            winner = simulate_elimination_match(
                home, away, precomputed_elim, rng, params, roster_multipliers, form_factor
            )
            winners.append(winner)
            # El perdedor ya tiene el label de la ronda anterior (r32 si es R32)

        # Los ganadores avanzan a la siguiente ronda
        if advance_label == "champion":
            # El ganador de la final es el campeón
            for team in winners:
                results[team] = "champion"
        else:
            for team in winners:
                results[team] = advance_label

        # Preparar la siguiente ronda: emparejar ganadores
        if advance_label != "champion":
            next_matchups = []
            for i in range(0, len(winners), 2):
                if i + 1 < len(winners):
                    next_matchups.append((winners[i], winners[i + 1]))
            current_matchups = next_matchups

    return results


# ---------------------------------------------------------------------------
# Agregación Monte Carlo (R6)
# ---------------------------------------------------------------------------

def run_simulation(
    fixtures: list[GroupFixture],
    params: DixonColesParams,
    n: int = DEFAULT_N_SIMULATIONS,
    seed: int = DEFAULT_SEED,
    roster_multipliers: dict[str, float] | None = None,
    _allow_small_n: bool = False,
    form_factor: Callable[[str, str], tuple[float, float]] | None = None,
) -> SimulationResult:
    """Ejecuta N simulaciones Monte Carlo del Mundial 2026 (R2, R3, R6, R9, R10).

    1. Valida n >= MIN_N_SIMULATIONS (salvo que ``_allow_small_n=True``, solo para tests).
    2. Deriva los 12 grupos desde los fixtures (R1).
    3. Precomputa λ y matrices DC UNA SOLA VEZ para los fixtures pendientes (R10).
    4. Para cada simulación:
       a. Usa marcadores reales para lo jugado; muestrea lo pendiente (R2, R3).
       b. Simula la fase de grupos → standings → clasificados (R4).
       c. Simula el bracket eliminatorio → campeón (R5).
    5. Agrega P(ronda) = conteo / N; calcula error MC = sqrt(p(1-p)/N) (R6).

    Args:
        fixtures: All 72 group-stage fixtures.
        params: Trained Dixon-Coles model parameters.
        n: Number of simulations (must be >= MIN_N_SIMULATIONS for production use).
        seed: RNG seed for reproducibility (injected, never from clock) (R3).
        roster_multipliers: Optional dict mapping team code to attack multiplier (R9).
        _allow_small_n: Internal flag; bypass the MIN_N_SIMULATIONS guard for unit tests
            that verify structural properties (never use in CLI or production paths).

    Returns:
        SimulationResult with probabilities and standard errors per team per round.

    Raises:
        ValueError: If n < MIN_N_SIMULATIONS and ``_allow_small_n`` is False.
        GroupStructureError: If fixtures don't form 12 valid groups.
    """
    if not _allow_small_n and n < MIN_N_SIMULATIONS:
        raise ValueError(
            f"n debe ser >= {MIN_N_SIMULATIONS}, se recibió n={n}."
        )

    # Derivar los 12 grupos desde los fixtures
    groups = derive_groups(fixtures)

    # Precomputar parámetros UNA SOLA VEZ (R10)
    precomputed = precompute_match_params(fixtures, params, roster_multipliers, form_factor)

    # RNG determinista con seed inyectada (R3)
    rng = np.random.default_rng(seed)

    # Todos los equipos en el torneo
    all_teams = sorted({t for grp in groups for t in grp.teams})

    # Contadores por equipo y ronda
    # Mapeamos las rondas a índices: group=0, r32=1, r16=2, qf=3, sf=4, final=5, champion=6
    round_order = {r: i for i, r in enumerate(ROUNDS)}

    counts: dict[str, dict[str, int]] = {
        team: {r: 0 for r in ROUNDS} for team in all_teams
    }

    # Bucle de N simulaciones
    for _ in range(n):
        sim_results = _simulate_one(groups, precomputed, params, rng, roster_multipliers, form_factor)

        for team, max_round in sim_results.items():
            if team not in counts:
                continue
            max_idx = round_order.get(max_round, 0)
            # Incrementar todos los contadores hasta la ronda alcanzada
            for r, r_idx in round_order.items():
                if r_idx <= max_idx:
                    counts[team][r] += 1

    # Agregar probabilidades y errores MC (R6)
    probabilities: dict[str, dict[str, float]] = {}
    std_errors: dict[str, dict[str, float]] = {}

    for team in all_teams:
        probs: dict[str, float] = {}
        ses: dict[str, float] = {}
        for r in ROUNDS:
            c = counts[team][r]
            p = c / n
            probs[r] = p
            ses[r] = float(np.sqrt(p * (1.0 - p) / n))
        probabilities[team] = probs
        std_errors[team] = ses

    return SimulationResult(
        n_simulations=n,
        probabilities=probabilities,
        std_errors=std_errors,
    )


# ---------------------------------------------------------------------------
# Carga del roster y multiplicadores (R9)
# ---------------------------------------------------------------------------

def load_roster_multipliers(
    roster_path: Path | str,
    player_factor_path: Path | str = Path("data/gold/player_factor.csv"),
) -> dict[str, float]:
    """Carga el multiplicador de ataque por equipo desde el roster y player_factor (R9).

    Args:
        roster_path: Path to the roster CSV (columns: team_code, scorer).
        player_factor_path: Path to the gold player_factor.csv.

    Returns:
        Dict mapping team code to attack multiplier. Teams not in the roster
        or without data get multiplier 1.0.
    """
    from ..players.factor import attack_multiplier, load_player_factor
    from ..players.normalize import normalize_goalscorer_events

    # Cargar player_factor
    pf_path = Path(player_factor_path)
    if not pf_path.is_file():
        return {}

    rates = load_player_factor(pf_path)

    # Cargar roster
    roster_path = Path(roster_path)
    if not roster_path.is_file():
        return {}

    roster: dict[str, list[str]] = {}
    with roster_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = (row.get("team_code") or "").strip()
            scorer = (row.get("scorer") or "").strip()
            if code and scorer:
                roster.setdefault(code, []).append(scorer)

    # Calcular multiplicador por equipo
    multipliers: dict[str, float] = {}
    for team_code, scorers in roster.items():
        mult = attack_multiplier(rates, team_code, scorers)
        multipliers[team_code] = mult

    return multipliers
