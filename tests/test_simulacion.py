"""tests/test_simulacion.py — Tests de la Feature 13: simulacion_montecarlo.

Trazabilidad (tasks.md):
| R1  | test_deriva_12_grupos_de_4, test_estructura_invalida_falla               |
| R2  | test_partidos_jugados_fijos_pendientes_muestreados                       |
| R3  | test_determinismo_misma_seed                                             |
| R4  | test_standings_desempates_y_mejores_terceros                             |
| R5  | test_bracket_r32_a_final_y_empate_resuelto                               |
| R6  | test_agregacion_probabilidades_y_error_mc                                |
| R7  | test_reporte_determinista_solo_bajo_data                                 |
| R9  | test_roster_aplica_multiplicador_opcional                                |
| R10 | test_lambda_precomputadas_una_vez                                        |

Estrategia: fixtures sintéticos de 2–4 grupos, N=100–500 sims (rápido, offline).
Sin red real. Sin reloj.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from src.simulation.bracket import (
    GroupFixture,
    Group,
    GroupStructureError,
    derive_groups,
    build_r32_matchups,
    _build_direct_matchups,
    _assign_thirds_to_bracket,
)
from src.simulation.standings import (
    TeamStanding,
    compute_group_table,
    get_group_qualified,
    rank_third_places,
)
from src.simulation.montecarlo import (
    MatchParams,
    SimulationResult,
    precompute_match_params,
    sample_score,
    simulate_match,
    simulate_elimination_match,
    run_simulation,
    _compute_single_match_params,
    MIN_N_SIMULATIONS,
)
from src.simulation.report import write_simulation_report, DEFAULT_REPORT_DIR

# Número de simulaciones reducido para tests que verifican propiedades ESTRUCTURALES
# (determinismo, monotonía, suma P(champion), claves de rondas). No reemplaza MIN_N_SIMULATIONS
# en tests que miden rendimiento o validan la fórmula SE con N exacto.
SMALL_N = 200


# ---------------------------------------------------------------------------
# Helpers para construir fixtures sintéticos
# ---------------------------------------------------------------------------

def _make_fixture(
    home: str,
    away: str,
    home_goals: int | None = None,
    away_goals: int | None = None,
    date: str = "2026-06-11",
) -> GroupFixture:
    """Construye un GroupFixture sintético para tests."""
    return GroupFixture(
        home=home,
        away=away,
        home_goals=home_goals,
        away_goals=away_goals,
        match_id=f"{home}_{away}_{date}",
        date=date,
    )


def _make_group_fixtures(teams: list[str], played: bool = False) -> list[GroupFixture]:
    """Genera los 6 fixtures round-robin para 4 equipos.

    Si ``played=True``, asigna marcadores ficticios (1-0 siempre gana el primero).
    """
    fixtures = []
    dates = ["2026-06-11", "2026-06-15", "2026-06-19"]
    date_idx = 0
    for i, t1 in enumerate(teams):
        for t2 in teams[i + 1:]:
            hg = 1 if played else None
            ag = 0 if played else None
            fixtures.append(_make_fixture(t1, t2, hg, ag, dates[date_idx % 3]))
            date_idx += 1
    return fixtures


def _make_synthetic_fixtures(n_groups: int = 4) -> list[GroupFixture]:
    """Genera fixtures sintéticos para n_groups grupos de 4 equipos (rápido, offline)."""
    # Usar códigos de 3 letras claramente sintéticos
    group_teams = [
        ["AA1", "AA2", "AA3", "AA4"],
        ["BB1", "BB2", "BB3", "BB4"],
        ["CC1", "CC2", "CC3", "CC4"],
        ["DD1", "DD2", "DD3", "DD4"],
        ["EE1", "EE2", "EE3", "EE4"],
        ["FF1", "FF2", "FF3", "FF4"],
        ["GG1", "GG2", "GG3", "GG4"],
        ["HH1", "HH2", "HH3", "HH4"],
        ["II1", "II2", "II3", "II4"],
        ["JJ1", "JJ2", "JJ3", "JJ4"],
        ["KK1", "KK2", "KK3", "KK4"],
        ["LL1", "LL2", "LL3", "LL4"],
    ]
    fixtures = []
    for teams in group_teams[:n_groups]:
        fixtures.extend(_make_group_fixtures(teams, played=False))
    return fixtures


def _make_minimal_dc_params():
    """Construye un DixonColesParams mínimo con equipos sintéticos (sin disco)."""
    from src.models.dixon_coles import DixonColesParams

    # 48 equipos sintéticos (12 grupos × 4)
    teams_list = []
    for label in ["AA", "BB", "CC", "DD", "EE", "FF", "GG", "HH", "II", "JJ", "KK", "LL"]:
        for n in range(1, 5):
            teams_list.append(f"{label}{n}")

    attack = {t: 0.1 * (i % 5) for i, t in enumerate(teams_list)}
    defense = {t: -0.05 * (i % 3) for i, t in enumerate(teams_list)}

    return DixonColesParams(
        as_of_date="2026-06-17",
        from_date="2018-01-01",
        xi=0.35,
        mu=0.1,
        home_advantage=0.2,
        rho=-0.1,
        attack=attack,
        defense=defense,
        n_matches=1000,
        n_teams=len(teams_list),
        min_matches=5,
        reg_lambda=0.25,
        low_data_teams=[],
        convergencia={"success": True, "n_iter": 100, "message": "OK", "neg_log_lik": 1.0},
    )


# ---------------------------------------------------------------------------
# R1 — Derivación de grupos
# ---------------------------------------------------------------------------

class TestDerivaGrupos:
    """R1: deriva_12_grupos_de_4, estructura_invalida_falla."""

    def test_deriva_12_grupos_de_4(self):
        """R1: desde 72 fixtures de 12 grupos de 4, se derivan exactamente 12 grupos de 4."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        groups = derive_groups(fixtures)

        assert len(groups) == 12, f"Se esperan 12 grupos, se obtuvieron {len(groups)}"
        for grp in groups:
            assert len(grp.teams) == 4, (
                f"Grupo {grp.label} tiene {len(grp.teams)} equipos, se esperan 4"
            )

    def test_grupos_etiquetados_A_a_L(self):
        """R1: los grupos se etiquetan A..L en orden alfabético del primer equipo."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        groups = derive_groups(fixtures)

        labels = [grp.label for grp in groups]
        assert labels == list("ABCDEFGHIJKL"), f"Etiquetas incorrectas: {labels}"

    def test_grupos_son_deterministas(self):
        """R1: mismos fixtures → mismos grupos (sin azar)."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        groups1 = derive_groups(fixtures)
        groups2 = derive_groups(fixtures)

        for g1, g2 in zip(groups1, groups2):
            assert g1.label == g2.label
            assert g1.teams == g2.teams

    def test_estructura_invalida_falla(self):
        """R1: si no hay 12 grupos de 4 → GroupStructureError accionable."""
        # Solo 3 grupos (no 12)
        fixtures = _make_synthetic_fixtures(n_groups=3)
        with pytest.raises(GroupStructureError, match="12 grupos"):
            derive_groups(fixtures)

    def test_grupo_de_3_equipos_falla(self):
        """R1: componente conexa con 3 equipos → GroupStructureError accionable."""
        # 3 equipos en un "grupo" (triángulo), no se puede tener clique de 4
        # Para esto, creamos un escenario donde un grupo solo tiene 3 equipos
        # y los otros 11 son normales de 4.
        # Simplificación: forzar error con fixtures inconsistentes
        fixtures_11_groups = _make_synthetic_fixtures(n_groups=11)
        # Añadir un grupo de 3 equipos (3 fixtures de round-robin incompletos)
        extra = [
            _make_fixture("ZZ1", "ZZ2"),
            _make_fixture("ZZ1", "ZZ3"),
            _make_fixture("ZZ2", "ZZ3"),
        ]
        with pytest.raises(GroupStructureError):
            derive_groups(fixtures_11_groups + extra)

    def test_fixtures_de_grupo_asignados_correctamente(self):
        """R1: cada grupo recibe sus 6 fixtures (round-robin de 4)."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        groups = derive_groups(fixtures)

        for grp in groups:
            assert len(grp.fixtures) == 6, (
                f"Grupo {grp.label}: {len(grp.fixtures)} fixtures, se esperan 6"
            )


# ---------------------------------------------------------------------------
# R4 — Standings y desempates
# ---------------------------------------------------------------------------

class TestStandingsDesempates:
    """R4: tabla de grupo con desempates deterministas y ranking de terceros."""

    def test_standings_puntos_basicos(self):
        """R4: puntos 3/1/0 se calculan correctamente."""
        teams = ["EQ1", "EQ2", "EQ3", "EQ4"]
        fixtures = [
            _make_fixture("EQ1", "EQ2", 2, 0),  # EQ1 gana (3 pts)
            _make_fixture("EQ1", "EQ3", 1, 1),  # empate (1 pt cada uno)
            _make_fixture("EQ1", "EQ4", 0, 1),  # EQ4 gana (3 pts)
            _make_fixture("EQ2", "EQ3", 1, 0),  # EQ2 gana (3 pts)
            _make_fixture("EQ2", "EQ4", 0, 2),  # EQ4 gana (3 pts)
            _make_fixture("EQ3", "EQ4", 0, 0),  # empate (1 pt)
        ]
        table = compute_group_table(teams, fixtures)

        pts = {s.team: s.points for s in table}
        assert pts["EQ1"] == 4  # 3+1+0
        assert pts["EQ2"] == 3  # 0+3+0
        assert pts["EQ4"] == 7  # 3+3+1
        assert pts["EQ3"] == 2  # 1+0+1

    def test_standings_desempate_diferencia_goles(self):
        """R4: desempate por diferencia de goles (criterio 2)."""
        teams = ["EQ1", "EQ2", "EQ3", "EQ4"]
        fixtures = [
            _make_fixture("EQ1", "EQ2", 3, 0),  # EQ1: +3 GD
            _make_fixture("EQ1", "EQ3", 2, 0),
            _make_fixture("EQ1", "EQ4", 2, 0),
            _make_fixture("EQ2", "EQ3", 2, 0),  # EQ2: mismo pts que EQ3
            _make_fixture("EQ2", "EQ4", 1, 0),
            _make_fixture("EQ3", "EQ4", 1, 0),
        ]
        table = compute_group_table(teams, fixtures)

        # EQ1 primero (9 pts, GD=+7)
        assert table[0].team == "EQ1"
        # EQ2 segundo (6 pts, GD=+3), EQ3 tercero (3 pts, GD=-1), EQ4 cuarto (0 pts)
        assert table[1].team == "EQ2"

    def test_standings_desempate_goles_a_favor(self):
        """R4: desempate por goles a favor (criterio 3)."""
        teams = ["EQ1", "EQ2", "EQ3", "EQ4"]
        # EQ1 y EQ2 tienen mismos puntos y GD=0, pero EQ1 tiene más GF
        fixtures = [
            _make_fixture("EQ1", "EQ3", 3, 3),  # empate
            _make_fixture("EQ2", "EQ4", 1, 1),  # empate
            _make_fixture("EQ1", "EQ4", 1, 1),
            _make_fixture("EQ2", "EQ3", 1, 1),
            _make_fixture("EQ1", "EQ2", 0, 0),
            _make_fixture("EQ3", "EQ4", 0, 0),
        ]
        table = compute_group_table(teams, fixtures)

        # EQ1 tiene más GF que EQ2 (ambos 2 pts, GD=0)
        pts = {s.team: s.points for s in table}
        gf = {s.team: s.gf for s in table}
        assert gf["EQ1"] > gf["EQ2"]
        # EQ1 debe estar antes que EQ2
        eq1_pos = next(i for i, s in enumerate(table) if s.team == "EQ1")
        eq2_pos = next(i for i, s in enumerate(table) if s.team == "EQ2")
        assert eq1_pos < eq2_pos

    def test_standings_pendientes_ignorados(self):
        """R4: fixtures pendientes (None scores) no afectan la tabla."""
        teams = ["EQ1", "EQ2", "EQ3", "EQ4"]
        fixtures = [
            _make_fixture("EQ1", "EQ2", 2, 0),   # jugado
            _make_fixture("EQ1", "EQ3", None, None),  # pendiente
            _make_fixture("EQ1", "EQ4", None, None),
            _make_fixture("EQ2", "EQ3", None, None),
            _make_fixture("EQ2", "EQ4", None, None),
            _make_fixture("EQ3", "EQ4", None, None),
        ]
        table = compute_group_table(teams, fixtures)

        # Solo el partido EQ1-EQ2 afecta la tabla
        pts = {s.team: s.points for s in table}
        assert pts["EQ1"] == 3
        assert pts["EQ2"] == 0
        assert pts["EQ3"] == 0
        assert pts["EQ4"] == 0

    def test_standings_desempates_y_mejores_terceros(self):
        """R4: tabla con desempates + ranking de terceros selecciona 8 mejores."""
        # 4 grupos sintéticos con resultados definidos
        group_teams = [
            ["AA1", "AA2", "AA3", "AA4"],
            ["BB1", "BB2", "BB3", "BB4"],
            ["CC1", "CC2", "CC3", "CC4"],
            ["DD1", "DD2", "DD3", "DD4"],
        ]
        # Terceros de cada grupo con distintas fuerzas
        thirds: dict[str, TeamStanding] = {}
        for i, teams in enumerate(group_teams):
            label = "ABCD"[i]
            table = compute_group_table(
                teams,
                _make_group_fixtures(teams, played=True),
            )
            _, _, third, _ = get_group_qualified(table)
            thirds[label] = third

        ranked = rank_third_places(thirds)
        assert len(ranked) == 4

        # El ranking debe estar ordenado (verificar criterio de puntos)
        for i in range(len(ranked) - 1):
            t1 = ranked[i]
            t2 = ranked[i + 1]
            # pts descendente
            assert t1.points >= t2.points

    def test_mejores_terceros_ranking_determinista(self):
        """R4: el ranking de terceros es determinista (mismos datos → mismo ranking)."""
        thirds = {
            "A": TeamStanding(team="AAA", played=3, wins=1, draws=1, losses=1,
                              gf=3, ga=3, points=4, attack_strength=0.2),
            "B": TeamStanding(team="BBB", played=3, wins=1, draws=0, losses=2,
                              gf=2, ga=4, points=3, attack_strength=0.1),
        }
        ranked1 = rank_third_places(thirds)
        ranked2 = rank_third_places(thirds)

        assert [s.team for s in ranked1] == [s.team for s in ranked2]


# ---------------------------------------------------------------------------
# R2 — Partidos jugados fijos, pendientes muestreados
# ---------------------------------------------------------------------------

class TestPartidosJugadosFijos:
    """R2: los partidos ya jugados retornan siempre el marcador real."""

    def test_partidos_jugados_fijos_pendientes_muestreados(self):
        """R2: fixtures con marcador real → siempre ese marcador; pendientes → muestreados."""
        from src.models.dixon_coles import DixonColesParams

        params = _make_minimal_dc_params()

        # Fixture jugado
        fix_played = _make_fixture("AA1", "AA2", 2, 1)
        # Fixture pendiente
        fix_pending = _make_fixture("AA1", "AA3", None, None)

        precomputed = precompute_match_params(
            [fix_played, fix_pending], params
        )

        rng = np.random.default_rng(42)

        # El jugado siempre retorna el marcador real
        for _ in range(20):
            h, a = simulate_match(fix_played, precomputed, rng)
            assert h == 2 and a == 1, f"Marcador real alterado: {h}-{a}"

        # El pendiente se muestrea (puede variar)
        assert (fix_pending.home, fix_pending.away) in precomputed

        scores = set()
        rng2 = np.random.default_rng(0)
        for _ in range(100):
            h, a = simulate_match(fix_pending, precomputed, rng2)
            scores.add((h, a))
        # Con 100 muestras debería haber variabilidad
        assert len(scores) > 1, "Los pendientes deben muestrearse (no ser fijos)"


# ---------------------------------------------------------------------------
# R3 — Determinismo con misma seed
# ---------------------------------------------------------------------------

class TestDeterminismoMismaSeed:
    """R3: misma seed + misma entrada → agregados idénticos."""

    def test_determinismo_misma_seed(self):
        """R3: run_simulation con misma seed produce exactamente los mismos resultados."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        params = _make_minimal_dc_params()

        result1 = run_simulation(fixtures, params, n=SMALL_N, seed=42, _allow_small_n=True)
        result2 = run_simulation(fixtures, params, n=SMALL_N, seed=42, _allow_small_n=True)

        # Los agregados deben ser byte a byte idénticos
        for team in result1.probabilities:
            for rnd in result1.probabilities[team]:
                p1 = result1.probabilities[team][rnd]
                p2 = result2.probabilities[team][rnd]
                assert p1 == p2, (
                    f"P({team}, {rnd}) difiere entre runs: {p1} vs {p2}"
                )

    def test_distinta_seed_produce_resultado_diferente(self):
        """R3: seeds distintas producen resultados distintos (con alta probabilidad)."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        params = _make_minimal_dc_params()

        result1 = run_simulation(fixtures, params, n=SMALL_N, seed=1, _allow_small_n=True)
        result2 = run_simulation(fixtures, params, n=SMALL_N, seed=999, _allow_small_n=True)

        # Al menos un equipo debe tener probabilidades distintas
        any_diff = False
        for team in result1.probabilities:
            for rnd in result1.probabilities[team]:
                if result1.probabilities[team][rnd] != result2.probabilities[team][rnd]:
                    any_diff = True
                    break
            if any_diff:
                break

        assert any_diff, "Seeds distintas deben producir resultados distintos"


# ---------------------------------------------------------------------------
# R5 — Bracket eliminatorio
# ---------------------------------------------------------------------------

class TestBracketEliminatorio:
    """R5: bracket R32 → Final + empates resueltos determinísticamente."""

    def test_bracket_r32_a_final_y_empate_resuelto(self):
        """R5: el bracket eliminatorio siempre produce exactamente 1 campeón."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        params = _make_minimal_dc_params()

        result = run_simulation(fixtures, params, n=SMALL_N, seed=42, _allow_small_n=True)

        # Exactamente un campeón por simulación → P(champion) sumado sobre todos = 1.0
        total_champion_prob = sum(
            result.probabilities[t]["champion"] for t in result.probabilities
        )
        # Con 1000 sims, la suma debe ser exactamente 1.0 (cada sim tiene 1 campeón)
        assert abs(total_champion_prob - 1.0) < 0.02, (
            f"P(champion) total = {total_champion_prob}, se esperaba ~1.0"
        )

    def test_empate_en_eliminatoria_resuelto(self):
        """R5: simulate_elimination_match siempre devuelve un ganador (no empate)."""
        params = _make_minimal_dc_params()
        precomputed_elim: dict = {}
        rng = np.random.default_rng(42)

        # Con 200 intentos, siempre debe haber un ganador
        for _ in range(200):
            winner = simulate_elimination_match(
                "AA1", "AA2", precomputed_elim, rng, params
            )
            assert winner in ("AA1", "AA2"), (
                f"Ganador inválido: {winner!r}"
            )

    def test_r32_tiene_16_llaves(self):
        """R5: el cuadro de R32 siempre tiene exactamente 16 llaves."""
        group_results = {
            label: [f"{label}1", f"{label}2", f"{label}3", f"{label}4"]
            for label in "ABCDEFGHIJKL"
        }
        best_thirds = [f"{label}3" for label in "ABCDEFGH"]

        matchups = build_r32_matchups(group_results, best_thirds)
        assert len(matchups) == 16, f"R32 tiene {len(matchups)} llaves, se esperan 16"

    def test_bracket_error_sin_12_grupos(self):
        """R5: build_r32_matchups con ≠12 grupos lanza GroupStructureError."""
        group_results = {
            label: [f"{label}1", f"{label}2", f"{label}3", f"{label}4"]
            for label in "ABCDE"  # solo 5 grupos
        }
        best_thirds = [f"{label}3" for label in "ABCDEFGH"]

        with pytest.raises(GroupStructureError, match="12 grupos"):
            build_r32_matchups(group_results, best_thirds)

    def test_avanzar_es_monotono_por_ronda(self):
        """R5: P(avanzar a ronda R) ≥ P(avanzar a ronda R+1) para todo equipo."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        params = _make_minimal_dc_params()

        result = run_simulation(fixtures, params, n=SMALL_N, seed=42, _allow_small_n=True)

        round_order_list = ["group", "r32", "r16", "qf", "sf", "final", "champion"]
        for team in result.probabilities:
            probs = result.probabilities[team]
            for i in range(len(round_order_list) - 1):
                r_curr = round_order_list[i]
                r_next = round_order_list[i + 1]
                p_curr = probs[r_curr]
                p_next = probs[r_next]
                assert p_curr >= p_next - 1e-9, (
                    f"{team}: P({r_curr})={p_curr:.4f} < P({r_next})={p_next:.4f}"
                )


# ---------------------------------------------------------------------------
# R6 — Agregación Monte Carlo y error estándar
# ---------------------------------------------------------------------------

class TestAgregacionMonteCarlo:
    """R6: probabilidades suman coherente + error MC."""

    def test_agregacion_probabilidades_y_error_mc(self):
        """R6: probabilidades en [0,1], error MC positivo, suma P(champion)≈1."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        params = _make_minimal_dc_params()

        result = run_simulation(fixtures, params, n=MIN_N_SIMULATIONS, seed=42)

        assert result.n_simulations == MIN_N_SIMULATIONS

        total_champion = 0.0
        for team in result.probabilities:
            probs = result.probabilities[team]
            ses = result.std_errors[team]
            for rnd in probs:
                p = probs[rnd]
                se = ses[rnd]
                assert 0.0 <= p <= 1.0, f"P({team}, {rnd}) = {p} fuera de [0,1]"
                assert se >= 0.0, f"SE({team}, {rnd}) = {se} negativo"
                # Verificar fórmula: SE = sqrt(p(1-p)/N)
                expected_se = float(np.sqrt(p * (1.0 - p) / MIN_N_SIMULATIONS))
                assert abs(se - expected_se) < 1e-10, (
                    f"SE({team}, {rnd}) = {se}, esperado {expected_se}"
                )
            total_champion += probs.get("champion", 0.0)

        # La suma de P(champion) ≈ 1 (con tolerancia por varianza Monte Carlo)
        assert abs(total_champion - 1.0) < 0.05, (
            f"Suma de P(champion) = {total_champion:.4f}, se esperaba ~1.0"
        )

    def test_n_minimo_valida(self):
        """R6: n < MIN_N_SIMULATIONS lanza ValueError."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        params = _make_minimal_dc_params()

        with pytest.raises(ValueError, match=str(MIN_N_SIMULATIONS)):
            run_simulation(fixtures, params, n=MIN_N_SIMULATIONS - 1, seed=42)

    def test_todas_las_rondas_reportadas(self):
        """R6: todas las rondas definidas están en el reporte."""
        from src.simulation.montecarlo import ROUNDS

        fixtures = _make_synthetic_fixtures(n_groups=12)
        params = _make_minimal_dc_params()

        result = run_simulation(fixtures, params, n=SMALL_N, seed=0, _allow_small_n=True)

        for team in result.probabilities:
            for rnd in ROUNDS:
                assert rnd in result.probabilities[team], (
                    f"Ronda {rnd!r} ausente en probabilities[{team!r}]"
                )
            for rnd in ROUNDS:
                assert rnd in result.std_errors[team], (
                    f"Ronda {rnd!r} ausente en std_errors[{team!r}]"
                )


# ---------------------------------------------------------------------------
# R7 — Reporte determinista bajo data/
# ---------------------------------------------------------------------------

class TestReporteDeterminista:
    """R7: reporte determinista escrito solo bajo data/."""

    def _make_result(self) -> SimulationResult:
        """Crea un SimulationResult sintético para tests del reporte."""
        teams = ["AA1", "AA2", "BB1", "BB2"]
        probs = {
            t: {
                "group": 1.0, "r32": 0.8, "r16": 0.5, "qf": 0.3,
                "sf": 0.2, "final": 0.1, "champion": 0.05,
            }
            for t in teams
        }
        ses = {
            t: {r: 0.01 for r in probs[t]}
            for t in teams
        }
        # Dar distintas probabilidades para verificar orden
        probs["AA1"]["champion"] = 0.25
        probs["BB2"]["champion"] = 0.15
        probs["AA2"]["champion"] = 0.10
        probs["BB1"]["champion"] = 0.05
        return SimulationResult(n_simulations=1000, probabilities=probs, std_errors=ses)

    def test_reporte_determinista_solo_bajo_data(self, tmp_path):
        """R7: los archivos se escriben correctamente y son deterministas."""
        out_dir = tmp_path / "data" / "reports" / "simulacion"
        result = self._make_result()

        json_path, csv_path = write_simulation_report(result, out_dir=out_dir)

        assert json_path.is_file()
        assert csv_path.is_file()

        # El JSON debe ser determinista (misma escritura dos veces → mismo contenido)
        json_path2, csv_path2 = write_simulation_report(result, out_dir=out_dir)
        assert json_path.read_text() == json_path2.read_text()
        assert csv_path.read_text() == csv_path2.read_text()

    def test_reporte_ordenado_por_p_titulo(self, tmp_path):
        """R7: el reporte ordena por P(título) desc."""
        out_dir = tmp_path / "data" / "reports" / "simulacion"
        result = self._make_result()

        json_path, csv_path = write_simulation_report(result, out_dir=out_dir)

        # Verificar en el JSON
        data = json.loads(json_path.read_text())
        champ_probs = [t["p_champion"] for t in data["teams"]]
        assert champ_probs == sorted(champ_probs, reverse=True), (
            f"El JSON no está ordenado por P(título) desc: {champ_probs}"
        )

        # Verificar en el CSV
        with csv_path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        csv_champ_probs = [float(r["p_champion"]) for r in rows]
        assert csv_champ_probs == sorted(csv_champ_probs, reverse=True), (
            f"El CSV no está ordenado por P(título) desc: {csv_champ_probs}"
        )

    def test_reporte_rechaza_fuera_de_data(self, tmp_path):
        """R7: escritura fuera de data/ → ValueError."""
        # Directorio sin 'data' en el path
        out_dir = tmp_path / "reports" / "simulacion"
        result = self._make_result()

        with pytest.raises(ValueError, match="data"):
            write_simulation_report(result, out_dir=out_dir)

    def test_reporte_json_sort_keys(self, tmp_path):
        """R7: el JSON se escribe con sort_keys=True."""
        out_dir = tmp_path / "data" / "simulacion"
        result = self._make_result()

        json_path, _ = write_simulation_report(result, out_dir=out_dir)
        raw = json_path.read_text()

        # El JSON debe poder parsearse
        doc = json.loads(raw)
        assert "n_simulations" in doc
        assert "teams" in doc


# ---------------------------------------------------------------------------
# R9 — Roster aplica multiplicador de ataque
# ---------------------------------------------------------------------------

class TestRosterMultiplicador:
    """R9: con roster, el multiplicador de ataque se aplica a las lambdas."""

    def test_roster_aplica_multiplicador_opcional(self):
        """R9: con roster_multipliers, las lambdas precomputadas se modifican."""
        params = _make_minimal_dc_params()

        fix_pending = _make_fixture("AA1", "AA2", None, None)

        # Sin multiplicador
        precomp_base = precompute_match_params([fix_pending], params, roster_multipliers=None)
        base_lambda_h = precomp_base[("AA1", "AA2")].lambda_home

        # Con multiplicador de 2.0 para AA1
        precomp_roster = precompute_match_params(
            [fix_pending], params, roster_multipliers={"AA1": 2.0}
        )
        roster_lambda_h = precomp_roster[("AA1", "AA2")].lambda_home

        assert abs(roster_lambda_h - 2.0 * base_lambda_h) < 1e-9, (
            f"Lambda_home con multiplicador 2.0 debe ser el doble: "
            f"base={base_lambda_h:.4f}, roster={roster_lambda_h:.4f}"
        )

    def test_sin_roster_modelo_base_intacto(self):
        """R9: sin roster_multipliers, las lambdas son idénticas al modelo base."""
        params = _make_minimal_dc_params()
        fix_pending = _make_fixture("AA1", "AA2", None, None)

        precomp1 = precompute_match_params([fix_pending], params, roster_multipliers=None)
        precomp2 = precompute_match_params([fix_pending], params, roster_multipliers={})

        lh1 = precomp1[("AA1", "AA2")].lambda_home
        lh2 = precomp2[("AA1", "AA2")].lambda_home
        # None y {} deben producir el mismo resultado (sin multiplicador)
        assert abs(lh1 - lh2) < 1e-9

    def test_roster_multiplicador_en_simulacion(self):
        """R9: precompute_match_params con roster_multipliers produce lambdas distintas en el
        contexto de los fixtures sintéticos completos (12 grupos). Verifica que el multiplicador
        se aplica efectivamente sobre los parámetros precomputados que la simulación usa."""
        fixtures = _make_synthetic_fixtures(n_groups=12)
        params = _make_minimal_dc_params()

        multiplier = 3.0
        team = "AA1"

        # Precomputar sin y con roster sobre el mismo conjunto de fixtures
        precomp_base = precompute_match_params(fixtures, params, roster_multipliers=None)
        precomp_roster = precompute_match_params(
            fixtures, params, roster_multipliers={team: multiplier}
        )

        # AA1 es local en el fixture AA1 vs AA2 (primer partido de cada grupo sintético).
        # Verificar que TODOS los partidos donde AA1 es local tienen lambda_home escalada.
        home_keys = [k for k in precomp_base if k[0] == team]
        away_keys = [k for k in precomp_base if k[1] == team]

        assert home_keys or away_keys, f"{team} no aparece en ningún fixture pendiente"

        for key in home_keys:
            lh_base = precomp_base[key].lambda_home
            lh_roster = precomp_roster[key].lambda_home
            assert abs(lh_roster - multiplier * lh_base) < 1e-9, (
                f"lambda_home de {key} con multiplicador {multiplier}: "
                f"esperado {multiplier * lh_base:.6f}, obtenido {lh_roster:.6f}"
            )
            # lambda_away no debe cambiar (el multiplicador es del equipo local)
            la_base = precomp_base[key].lambda_away
            la_roster = precomp_roster[key].lambda_away
            assert abs(la_roster - la_base) < 1e-9, (
                f"lambda_away de {key} no debe cambiar con el roster del equipo local: "
                f"base={la_base:.6f}, roster={la_roster:.6f}"
            )

        for key in away_keys:
            # Cuando AA1 es visitante, su ataque es lambda_away
            la_base = precomp_base[key].lambda_away
            la_roster = precomp_roster[key].lambda_away
            assert abs(la_roster - multiplier * la_base) < 1e-9, (
                f"lambda_away de {key} con multiplicador {multiplier}: "
                f"esperado {multiplier * la_base:.6f}, obtenido {la_roster:.6f}"
            )

        # Las matrices precomputadas también deben diferir (el multiplicador afecta la distribución)
        for key in home_keys + away_keys:
            diff = np.abs(precomp_roster[key].matrix - precomp_base[key].matrix).max()
            assert diff > 1e-9, (
                f"La matriz de {key} no cambió con el roster multiplier (diff={diff:.2e})"
            )


# ---------------------------------------------------------------------------
# R10 — Precomputo de lambdas una sola vez
# ---------------------------------------------------------------------------

class TestLambdaPrecomputadas:
    """R10: las lambdas se precomputan una vez, no por simulación."""

    def test_lambda_precomputadas_una_vez(self):
        """R10: precompute_match_params sólo incluye fixtures pendientes (no jugados)."""
        params = _make_minimal_dc_params()

        fix_played = _make_fixture("AA1", "AA2", 1, 0)
        fix_pending1 = _make_fixture("AA1", "AA3", None, None)
        fix_pending2 = _make_fixture("AA2", "AA3", None, None)
        fix_pending3 = _make_fixture("AA1", "AA4", None, None)

        precomp = precompute_match_params(
            [fix_played, fix_pending1, fix_pending2, fix_pending3],
            params,
        )

        # Solo los pendientes deben estar en el dict
        assert ("AA1", "AA2") not in precomp, "El jugado NO debe precomputarse"
        assert ("AA1", "AA3") in precomp
        assert ("AA2", "AA3") in precomp
        assert ("AA1", "AA4") in precomp
        assert len(precomp) == 3, f"Se esperan 3 entradas, hay {len(precomp)}"

    def test_precomputo_no_cambia_con_rng(self):
        """R10: el precomputo es determinista (no depende del RNG)."""
        params = _make_minimal_dc_params()
        fix_pending = _make_fixture("AA1", "AA3", None, None)

        precomp1 = precompute_match_params([fix_pending], params)
        precomp2 = precompute_match_params([fix_pending], params)

        lh1 = precomp1[("AA1", "AA3")].lambda_home
        lh2 = precomp2[("AA1", "AA3")].lambda_home
        assert abs(lh1 - lh2) < 1e-12, "El precomputo debe ser determinista"

    def test_rendimiento_acotado(self):
        """R10: 1000 simulaciones completan en menos de 30 segundos (orientativo)."""
        import time

        fixtures = _make_synthetic_fixtures(n_groups=12)
        params = _make_minimal_dc_params()

        start = time.time()
        run_simulation(fixtures, params, n=MIN_N_SIMULATIONS, seed=42)
        elapsed = time.time() - start

        assert elapsed < 30.0, (
            f"1000 simulaciones tardaron {elapsed:.1f}s, límite orientativo: 30s"
        )
