"""Feature 11 — factor_jugadores, R2–R6 y R8.

Tests 100% offline y deterministas: fixture ``goalscorers_sample.csv`` como
fuente de datos; ``as_of_date`` inyectado; cero red real y cero reloj.
Mapeo de tasks.md:
  R2  → test_normaliza_excluye_own_goals_y_mapea_equipo, test_descarta_malformados_con_motivo
  R3  → test_cuotas_suman_uno_por_equipo, test_anti_fuga_eventos_posteriores_no_cambian
  R4  → test_anytime_scorer_thinning_poisson_oraculo
  R5  → test_multiplicador_roster_y_default_identidad
  R6  → test_artefacto_gold_determinista
  R8  → cubierto transversalmente (sin red, sin reloj, escritura bajo data/)
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from src.players.normalize import (
    REASON_INCOMPLETE_COLUMNS,
    REASON_INVALID_DATE,
    REASON_OWN_GOAL,
    REASON_EMPTY_SCORER,
    REASON_UNKNOWN_TEAM,
    GoalEvent,
    NormalizeReport,
    normalize_goalscorer_events,
)
from src.players.factor import (
    PlayerRate,
    AnytimeScorer,
    SHARE_SUM_TOLERANCE,
    attack_multiplier,
    build_player_rates,
    build_player_factor,
    compute_anytime_scorers,
    load_player_factor,
    save_player_factor,
)
from src.models.dixon_coles import DCConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = (FIXTURES / "goalscorers_sample.csv").read_text(encoding="utf-8")

AS_OF = "2023-01-01"  # cubre todos los eventos del fixture (2022-11-xx)
XI = DCConfig.xi       # 0.35


# ---------------------------------------------------------------------------
# R2: test_normaliza_excluye_own_goals_y_mapea_equipo
# ---------------------------------------------------------------------------


def test_normaliza_excluye_own_goals_y_mapea_equipo():
    """R2: own_goal==TRUE excluidos del crédito; team mapeado a código FIFA."""
    events, report = normalize_goalscorer_events(SAMPLE)

    # El own_goal de Australia (Craig Goodwin) debe excluirse
    scorers = [(e.team_code, e.scorer) for e in events]
    assert ("AUS", "Craig Goodwin") not in scorers
    assert REASON_OWN_GOAL in report.discarded_by_reason
    assert report.discarded_by_reason[REASON_OWN_GOAL] >= 1

    # Los nombres de equipo se mapean a código FIFA
    team_codes = {e.team_code for e in events}
    assert all(len(c) == 3 and c.isupper() for c in team_codes), (
        f"Se esperan códigos FIFA de 3 letras; encontrado: {team_codes}"
    )

    # Argentina mapeada a ARG
    arg_events = [e for e in events if e.team_code == "ARG"]
    assert len(arg_events) > 0
    # Ningún evento tiene 'Argentina' como team_code
    assert "Argentina" not in team_codes


def test_normaliza_penalty_flag_conservado():
    """R2: el flag penalty se conserva en los eventos válidos."""
    events, _ = normalize_goalscorer_events(SAMPLE)

    # El primer evento de Messi en el fixture es un penalti
    messi_events = [e for e in events if e.scorer == "Lionel Messi" and e.team_code == "ARG"]
    assert any(e.penalty for e in messi_events), "Debe haber al menos un penalti de Messi"
    assert any(not e.penalty for e in messi_events), "Debe haber al menos un gol no penalti de Messi"


# ---------------------------------------------------------------------------
# R2: test_descarta_malformados_con_motivo
# ---------------------------------------------------------------------------


def test_descarta_malformados_con_motivo():
    """R2: filas malformadas (fecha inválida, scorer vacío, equipo desconocido) descartan con motivo."""
    events, report = normalize_goalscorer_events(SAMPLE)

    # El fixture tiene: fecha inválida, scorer vacío, own_goal
    assert report.n_discarded > 0
    assert report.n_valid + report.n_discarded == report.n_rows_total

    # La fila con fecha 'invalid-date' debe descartarse
    assert REASON_INVALID_DATE in report.discarded_by_reason

    # La fila con scorer vacío (Mexico, minuto 45 en el fixture) debe descartarse
    assert REASON_EMPTY_SCORER in report.discarded_by_reason


def test_descarta_no_aborta_lote():
    """R2: el lote continúa aunque haya filas corruptas."""
    bad_csv = (
        "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n"
        "2022-01-01,Argentina,Brazil,Argentina,Lionel Messi,10,False,False\n"
        "not-a-date,Argentina,Brazil,Argentina,Messi,5,False,False\n"
        "2022-01-02,France,England,France,Kylian Mbappe,30,True,False\n"  # own_goal
        "2022-01-03,Spain,Germany,Spain,Sergio Ramos,60,False,False\n"
    )
    events, report = normalize_goalscorer_events(bad_csv)
    # Messi del primer evento y Ramos deberían pasar (si España está en DATASET_ALIASES)
    assert report.n_valid >= 1
    assert report.n_discarded >= 2  # fecha inválida + own_goal


def test_descarta_columnas_incompletas():
    """R2: filas con columnas incompletas se descartan con motivo REASON_INCOMPLETE_COLUMNS."""
    bad_csv = (
        "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n"
        "2022-01-01,Argentina,Brazil,Argentina,Messi\n"  # solo 5 columnas
    )
    _, report = normalize_goalscorer_events(bad_csv)
    assert REASON_INCOMPLETE_COLUMNS in report.discarded_by_reason


# ---------------------------------------------------------------------------
# R3: test_cuotas_suman_uno_por_equipo
# ---------------------------------------------------------------------------


def test_cuotas_suman_uno_por_equipo():
    """R3: la suma de shares de los jugadores de un equipo es ≈ 1 (tol 1e-9)."""
    events, _ = normalize_goalscorer_events(SAMPLE)
    rates = build_player_rates(events, AS_OF, xi=XI)

    assert len(rates) > 0

    # Agrupar por equipo y verificar suma
    from collections import defaultdict
    by_team: dict[str, float] = defaultdict(float)
    for r in rates:
        by_team[r.team_code] += r.share

    for team_code, total in by_team.items():
        assert abs(total - 1.0) < SHARE_SUM_TOLERANCE, (
            f"Equipo {team_code}: suma de shares = {total:.12f}, esperado ≈ 1.0"
        )


def test_cuotas_orden_determinista():
    """R3: el resultado está ordenado por (team_code ASC, share DESC, scorer ASC)."""
    events, _ = normalize_goalscorer_events(SAMPLE)
    rates = build_player_rates(events, AS_OF, xi=XI)

    for i in range(len(rates) - 1):
        a, b = rates[i], rates[i + 1]
        if a.team_code == b.team_code:
            # Mismo equipo: share debe ser >= (desc) o mismo share → scorer ASC
            if abs(a.share - b.share) < 1e-12:
                assert a.scorer <= b.scorer, f"Mismo share, scorer debe ser ASC: {a.scorer!r} > {b.scorer!r}"
            else:
                assert a.share >= b.share, f"Share DESC violado: {a.share} < {b.share}"
        else:
            assert a.team_code <= b.team_code, f"team_code ASC violado: {a.team_code!r} > {b.team_code!r}"


# ---------------------------------------------------------------------------
# R3: test_anti_fuga_eventos_posteriores_no_cambian
# ---------------------------------------------------------------------------


def test_anti_fuga_eventos_posteriores_no_cambian():
    """R3: eventos con fecha >= as_of_date no cambian la tabla (anti-fuga)."""
    # Crear eventos manuales con fechas alrededor del corte
    from src.players.normalize import GoalEvent

    as_of = "2022-12-01"

    events_before = [
        GoalEvent(date="2022-11-01", team_code="ARG", scorer="Messi", penalty=False),
        GoalEvent(date="2022-11-15", team_code="ARG", scorer="Messi", penalty=False),
    ]
    events_after = [
        GoalEvent(date="2022-12-01", team_code="ARG", scorer="Messi", penalty=False),  # >= as_of
        GoalEvent(date="2023-01-01", team_code="ARG", scorer="Messi", penalty=False),  # > as_of
    ]

    rates_before = build_player_rates(events_before, as_of, xi=XI)
    rates_combined = build_player_rates(events_before + events_after, as_of, xi=XI)

    assert len(rates_before) == len(rates_combined)
    for rb, rc in zip(rates_before, rates_combined):
        assert rb.team_code == rc.team_code
        assert rb.scorer == rc.scorer
        assert abs(rb.goals_weighted - rc.goals_weighted) < 1e-12, (
            f"goals_weighted cambió con eventos posteriores: {rb.goals_weighted} != {rc.goals_weighted}"
        )
        assert abs(rb.share - rc.share) < 1e-12


def test_sin_eventos_antes_de_as_of_retorna_lista_vacia():
    """R3: si todos los eventos son >= as_of_date, el resultado es lista vacía."""
    from src.players.normalize import GoalEvent

    future_events = [
        GoalEvent(date="2025-01-01", team_code="ARG", scorer="Messi", penalty=False),
    ]
    rates = build_player_rates(future_events, "2024-01-01", xi=XI)
    assert rates == []


# ---------------------------------------------------------------------------
# R4: test_anytime_scorer_thinning_poisson_oraculo
# ---------------------------------------------------------------------------


def test_anytime_scorer_thinning_poisson_oraculo():
    """R4: P(marca≥1) = 1 − exp(−λ_jugador) verificado con oráculo analítico."""
    from src.players.normalize import GoalEvent

    # Fixture controlado: 2 jugadores de ARG con historial conocido
    as_of = "2023-01-01"
    events = [
        # Messi: 3 goles, Alvarez: 1 gol (antes de as_of)
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="Messi", penalty=False),
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="Messi", penalty=False),
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="Messi", penalty=False),
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="Alvarez", penalty=False),
    ]

    rates = build_player_rates(events, as_of, xi=0.0)  # xi=0 → pesos = 1.0 (sin decaimiento)

    # Con xi=0: goles ponderados = goles contados
    # Messi: 3/4 = 0.75, Alvarez: 1/4 = 0.25
    messi_rate = next(r for r in rates if r.scorer == "Messi")
    alvarez_rate = next(r for r in rates if r.scorer == "Alvarez")
    assert abs(messi_rate.share - 0.75) < 1e-9
    assert abs(alvarez_rate.share - 0.25) < 1e-9

    # Oráculo con lambda_equipo = 1.5
    lambda_team = 1.5
    scorers = compute_anytime_scorers(rates, lambda_team, "ARG")

    messi_scorer = next(s for s in scorers if s.scorer == "Messi")
    alvarez_scorer = next(s for s in scorers if s.scorer == "Alvarez")

    # Verificación exacta del thinning de Poisson
    lam_messi = 0.75 * lambda_team
    lam_alvarez = 0.25 * lambda_team
    expected_prob_messi = 1.0 - math.exp(-lam_messi)
    expected_prob_alvarez = 1.0 - math.exp(-lam_alvarez)

    assert abs(messi_scorer.lambda_player - lam_messi) < 1e-12
    assert abs(messi_scorer.prob_score - expected_prob_messi) < 1e-12
    assert abs(alvarez_scorer.lambda_player - lam_alvarez) < 1e-12
    assert abs(alvarez_scorer.prob_score - expected_prob_alvarez) < 1e-12


def test_anytime_scorer_top_k():
    """R4: top_k filtra correctamente la cantidad de jugadores devueltos."""
    from src.players.normalize import GoalEvent

    events = [
        GoalEvent(date="2022-06-01", team_code="FRA", scorer="Mbappe", penalty=False),
        GoalEvent(date="2022-06-01", team_code="FRA", scorer="Giroud", penalty=False),
        GoalEvent(date="2022-06-01", team_code="FRA", scorer="Griezmann", penalty=False),
    ]
    rates = build_player_rates(events, "2023-01-01", xi=0.0)
    scorers_all = compute_anytime_scorers(rates, 1.5, "FRA")
    scorers_top2 = compute_anytime_scorers(rates, 1.5, "FRA", top_k=2)
    assert len(scorers_all) == 3
    assert len(scorers_top2) == 2
    # El top-2 debe ser los 2 de mayor probabilidad
    assert scorers_top2[0].prob_score >= scorers_top2[1].prob_score


def test_anytime_scorer_orden_descendente():
    """R4: los scorers están ordenados por prob_score DESC."""
    events, _ = normalize_goalscorer_events(SAMPLE)
    rates = build_player_rates(events, AS_OF, xi=XI)
    if not rates:
        pytest.skip("No hay tasas calculadas para el fixture")
    team_code = rates[0].team_code
    scorers = compute_anytime_scorers(rates, 1.5, team_code)
    for i in range(len(scorers) - 1):
        assert scorers[i].prob_score >= scorers[i + 1].prob_score


# ---------------------------------------------------------------------------
# R5: test_multiplicador_roster_y_default_identidad
# ---------------------------------------------------------------------------


def test_multiplicador_roster_y_default_identidad():
    """R5: sin roster → exactamente 1.0; con roster → min(1.0, Σ shares disponibles)."""
    from src.players.normalize import GoalEvent

    events = [
        GoalEvent(date="2022-06-01", team_code="BRA", scorer="Richarlison", penalty=False),
        GoalEvent(date="2022-06-01", team_code="BRA", scorer="Richarlison", penalty=False),
        GoalEvent(date="2022-06-01", team_code="BRA", scorer="Vinicius", penalty=False),
    ]
    rates = build_player_rates(events, "2023-01-01", xi=0.0)

    # Con xi=0: Richarlison 2/3, Vinicius 1/3
    # Sin roster → identidad exacta 1.0
    mult_none = attack_multiplier(rates, "BRA", roster=None)
    assert mult_none == 1.0

    # Con roster que incluye solo Richarlison: 2/3
    mult_richarlison = attack_multiplier(rates, "BRA", roster=["Richarlison"])
    assert abs(mult_richarlison - 2.0 / 3.0) < 1e-9

    # Con roster completo: min(1.0, 1.0) = 1.0
    mult_full = attack_multiplier(rates, "BRA", roster=["Richarlison", "Vinicius"])
    assert abs(mult_full - 1.0) < 1e-9

    # Con roster vacío: 0.0
    mult_empty = attack_multiplier(rates, "BRA", roster=[])
    assert mult_empty == 0.0


def test_multiplicador_acotado_a_uno():
    """R5: el multiplicador nunca supera 1.0 aunque los shares no cubran exactamente el total."""
    from src.players.normalize import GoalEvent

    events = [
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="A", penalty=False),
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="B", penalty=False),
    ]
    rates = build_player_rates(events, "2023-01-01", xi=0.0)

    # Roster con jugadores desconocidos que no están en rates: sum = 0
    mult_unknown = attack_multiplier(rates, "ARG", roster=["Unknown1", "Unknown2"])
    assert mult_unknown == 0.0

    # Roster con todos los jugadores: ≤ 1.0 (en este caso = 1.0)
    mult_all = attack_multiplier(rates, "ARG", roster=["A", "B"])
    assert mult_all <= 1.0


def test_multiplicador_equipo_sin_datos():
    """R5: equipo sin datos en rates → multiplicador 0.0 si hay roster."""
    from src.players.normalize import GoalEvent

    events = [
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="Messi", penalty=False),
    ]
    rates = build_player_rates(events, "2023-01-01", xi=0.0)

    # Roster de equipo diferente (BRA) que no tiene datos → 0.0
    mult = attack_multiplier(rates, "BRA", roster=["Neymar"])
    assert mult == 0.0

    # Sin roster → 1.0 (identidad para cualquier equipo)
    mult_none = attack_multiplier(rates, "BRA", roster=None)
    assert mult_none == 1.0


# ---------------------------------------------------------------------------
# R6: test_artefacto_gold_determinista
# ---------------------------------------------------------------------------


def test_artefacto_gold_determinista(tmp_path):
    """R6: misma entrada → mismo contenido byte a byte; escritura bajo data/."""
    events, _ = normalize_goalscorer_events(SAMPLE)
    out_path = tmp_path / "data" / "gold" / "player_factor.csv"

    rates1 = build_player_factor(events, AS_OF, xi=XI, out_path=out_path)
    content1 = out_path.read_bytes()

    rates2 = build_player_factor(events, AS_OF, xi=XI, out_path=out_path)
    content2 = out_path.read_bytes()

    assert content1 == content2, "Mismo input debe producir mismo CSV byte a byte"


def test_artefacto_gold_columnas_correctas(tmp_path):
    """R6: el gold tiene exactamente las columnas especificadas en el diseño."""
    events, _ = normalize_goalscorer_events(SAMPLE)
    out_path = tmp_path / "data" / "gold" / "player_factor.csv"

    build_player_factor(events, AS_OF, xi=XI, out_path=out_path)

    with out_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames is not None
        assert list(reader.fieldnames) == ["as_of_date", "team_code", "scorer", "goals_weighted", "share"]
        rows = list(reader)
    assert len(rows) > 0
    # Verificar as_of_date en todas las filas
    for row in rows:
        assert row["as_of_date"] == AS_OF


def test_artefacto_gold_orden_determinista(tmp_path):
    """R6: orden (team_code ASC, share DESC, scorer ASC) en el gold."""
    events, _ = normalize_goalscorer_events(SAMPLE)
    out_path = tmp_path / "data" / "gold" / "player_factor.csv"

    build_player_factor(events, AS_OF, xi=XI, out_path=out_path)
    rates = load_player_factor(out_path)

    for i in range(len(rates) - 1):
        a, b = rates[i], rates[i + 1]
        if a.team_code == b.team_code:
            if abs(a.share - b.share) > 1e-12:
                assert a.share >= b.share, f"share DESC violado en gold: {a.share} < {b.share}"
        else:
            assert a.team_code <= b.team_code, f"team_code ASC violado en gold"


def test_artefacto_gold_escritura_fuera_de_data_rechazada(tmp_path):
    """R6/R8: escritura fuera de data/ levanta ValueError."""
    events, _ = normalize_goalscorer_events(SAMPLE)
    bad_path = tmp_path / "output" / "player_factor.csv"

    with pytest.raises(ValueError, match="data/"):
        build_player_factor(events, AS_OF, xi=XI, out_path=bad_path)


def test_load_player_factor_roundtrip(tmp_path):
    """R6: save → load produce la misma lista de PlayerRate."""
    from src.players.normalize import GoalEvent

    events = [
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="Messi", penalty=False),
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="Alvarez", penalty=False),
    ]
    out_path = tmp_path / "data" / "gold" / "player_factor.csv"
    rates_orig = build_player_factor(events, "2023-01-01", xi=0.0, out_path=out_path)
    rates_loaded = load_player_factor(out_path)

    assert len(rates_orig) == len(rates_loaded)
    for orig, loaded in zip(rates_orig, rates_loaded):
        assert orig.team_code == loaded.team_code
        assert orig.scorer == loaded.scorer
        assert abs(orig.goals_weighted - loaded.goals_weighted) < 1e-6
        assert abs(orig.share - loaded.share) < 1e-6


def test_load_player_factor_no_existe(tmp_path):
    """R6: si el gold no existe, load_player_factor levanta FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_player_factor(tmp_path / "data" / "gold" / "nonexistent.csv")


# ---------------------------------------------------------------------------
# R8: Sin red real, without datetime.now()
# ---------------------------------------------------------------------------


def test_sin_reloj_en_build_player_rates(monkeypatch):
    """R8: build_player_rates no usa el reloj del sistema — as_of inyectado (R8).

    El resultado debe ser determinista para el mismo as_of_date inyectado sin
    depender del instante de ejecución; verificamos que el resultado no cambia
    entre dos llamadas con las mismas entradas.
    """
    from src.players.normalize import GoalEvent

    events = [
        GoalEvent(date="2022-06-01", team_code="ARG", scorer="Messi", penalty=False),
        GoalEvent(date="2022-06-15", team_code="ARG", scorer="Alvarez", penalty=False),
    ]

    # Ejecutar dos veces con el mismo as_of; el resultado debe ser idéntico
    rates_1 = build_player_rates(events, "2023-01-01", xi=0.35)
    rates_2 = build_player_rates(events, "2023-01-01", xi=0.35)

    assert len(rates_1) == len(rates_2)
    for r1, r2 in zip(rates_1, rates_2):
        assert r1.team_code == r2.team_code
        assert r1.scorer == r2.scorer
        assert r1.goals_weighted == r2.goals_weighted
        assert r1.share == r2.share

    # Verificar que el módulo factor.py no importa datetime.now a nivel de módulo
    import src.players.factor as factor_mod
    import inspect
    source = inspect.getsource(factor_mod.build_player_rates)
    assert "datetime.now" not in source, "build_player_rates no debe usar datetime.now()"
