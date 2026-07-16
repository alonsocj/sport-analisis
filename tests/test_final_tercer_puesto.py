"""tests/test_final_tercer_puesto.py — Feature 34: Final + 3er puesto WC2026.

Trazabilidad R<n> → test (ver specs/final_tercer_puesto/):
- R1 fixtures r2/r3p         → TestFixturesFinal3P
- R2 detección 3P           → TestDeteccion3P
- R3 dead-rubber            → TestDeadRubber
- R4 simulador cruce fijo   → TestSimulateFixture
- R5 empate→ET→penales      → TestSimulatePathway
- R6 artefactos             → TestSimArtifact
- R7/R8 CLI + no-regresión  → tests/test_cli_simulate_match.py (+ TestNoRegresion aquí)
- R9 app tab Final          → tests/test_app_final.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers compartidos
# ---------------------------------------------------------------------------

def _dc_params():
    """DixonColesParams sintético: favorito claro (STRONG) vs débil (WEAK)."""
    from src.models.dixon_coles import DixonColesParams

    attack = {"STRONG": 0.6, "WEAK": -0.4, "MID": 0.0, "MID2": 0.05}
    defense = {"STRONG": -0.5, "WEAK": 0.3, "MID": 0.0, "MID2": -0.02}
    return DixonColesParams(
        as_of_date="2026-07-15",
        from_date="2018-01-01",
        xi=0.35,
        mu=0.1,
        home_advantage=0.0,  # KO en campo neutral
        rho=-0.1,
        attack=attack,
        defense=defense,
        n_matches=1000,
        n_teams=len(attack),
        min_matches=5,
        reg_lambda=0.25,
        low_data_teams=[],
        convergencia={"success": True, "n_iter": 100, "message": "OK", "neg_log_lik": 1.0},
    )


# ---------------------------------------------------------------------------
# R3 — Dead-rubber (amortiguación de motivación del 3er puesto)
# ---------------------------------------------------------------------------

class TestDeadRubber:
    """R3: apply_dead_rubber encoge la ventaja del favorito + bump de apertura."""

    def test_dead_rubber_off_identidad(self):
        """delta=0, kappa=1 → identidad byte-idéntica."""
        from src.models.dead_rubber import (
            DeadRubber,
            OFF,
            apply_openness,
            shrink_toward,
        )

        assert shrink_toward(0.6, 0.0, 0.0) == 0.6
        assert apply_openness(1.5, 1.1, 1.0) == (1.5, 1.1)
        assert OFF.delta == 0.0 and OFF.kappa == 1.0
        # defaults documentados (base histórica 3er puesto)
        assert DeadRubber().delta > 0.0 and DeadRubber().kappa > 1.0

    def test_dead_rubber_full_shrink_va_a_media(self):
        """delta=1 → colapsa completamente hacia la media (sin ventaja)."""
        from src.models.dead_rubber import shrink_toward

        assert shrink_toward(0.6, 0.1, 1.0) == pytest.approx(0.1)

    def test_dead_rubber_sube_goles(self):
        """kappa>1 → ambas lambdas suben (partido más abierto)."""
        from src.models.dead_rubber import apply_openness

        lh, la = apply_openness(1.4, 1.0, 1.12)
        assert lh > 1.4 and la > 1.0
        assert lh + la > 2.4

    def test_dead_rubber_baja_prob_favorito(self):
        """shrink_strengths aplana la ventaja → P(gana favorito) baja."""
        from src.models.dead_rubber import shrink_strengths
        from src.models.dixon_coles import match_rates, score_matrix

        p = _dc_params()
        mean_a = float(np.mean(list(p.attack.values())))
        mean_d = float(np.mean(list(p.defense.values())))

        def win_probs(ah, dh, aa, da):
            lh, la = match_rates(p.mu, 0.0, ah, dh, aa, da, 0.0)
            m = score_matrix(float(lh), float(la), p.rho, 10)
            return float(np.tril(m, -1).sum()), float(np.triu(m, 1).sum())

        base_h, base_a = win_probs(p.attack["STRONG"], p.defense["STRONG"],
                                   p.attack["WEAK"], p.defense["WEAK"])
        ah, dh = shrink_strengths(p.attack["STRONG"], p.defense["STRONG"], mean_a, mean_d, 0.45)
        aa, da = shrink_strengths(p.attack["WEAK"], p.defense["WEAK"], mean_a, mean_d, 0.45)
        damp_h, damp_a = win_probs(ah, dh, aa, da)

        assert base_h > base_a  # STRONG es el favorito
        assert damp_h < base_h  # dead-rubber recorta la ventaja del favorito
        assert (base_h - base_a) > (damp_h - damp_a)  # la brecha se estrecha


# ---------------------------------------------------------------------------
# R4 — Simulador Monte Carlo de un enfrentamiento fijo
# ---------------------------------------------------------------------------

class TestSimulateFixture:
    """R4: simulate_fixture agrega P(ganador), marcador modal, mercados, error MC."""

    def test_sim_determinista_misma_seed(self):
        """Misma seed → resultado idéntico (RNG inyectado, sin reloj)."""
        from src.simulation.match_sim import simulate_fixture

        p = _dc_params()
        a = simulate_fixture("STRONG", "WEAK", p, n=4000, seed=7, _allow_small_n=True)
        b = simulate_fixture("STRONG", "WEAK", p, n=4000, seed=7, _allow_small_n=True)
        assert a.p_home == b.p_home
        assert a.modal_score == b.modal_score
        assert a.top_scores == b.top_scores
        # seed distinta → distinto (con altísima probabilidad)
        c = simulate_fixture("STRONG", "WEAK", p, n=4000, seed=8, _allow_small_n=True)
        assert c.p_home != a.p_home or c.e_goals != a.e_goals

    def test_sim_probs_suman_uno(self):
        """El KO siempre tiene ganador: p_home + p_away = 1; reg 90' suma 1."""
        from src.simulation.match_sim import simulate_fixture

        p = _dc_params()
        r = simulate_fixture("STRONG", "WEAK", p, n=4000, seed=1, _allow_small_n=True)
        assert r.p_home + r.p_away == pytest.approx(1.0)
        assert r.p_home_reg + r.p_draw_reg + r.p_away_reg == pytest.approx(1.0)
        assert 0.0 <= r.p_home <= 1.0

    def test_sim_crosscheck_vs_analitico(self):
        """La frecuencia muestreada de victoria local en 90' ≈ probabilidad analítica DC."""
        from src.simulation.match_sim import match_matrix, simulate_fixture

        p = _dc_params()
        m = match_matrix("STRONG", "WEAK", p)
        analytic_home = float(np.tril(m, -1).sum())

        r = simulate_fixture("STRONG", "WEAK", p, n=30000, seed=3)
        se = r.std_err["p_home_reg"]
        assert abs(r.p_home_reg - analytic_home) <= 4.0 * se + 0.01

    def test_sim_valida_n_min(self):
        """n < MIN sin flag interno → ValueError."""
        from src.simulation.match_sim import simulate_fixture
        from src.simulation.montecarlo import MIN_N_SIMULATIONS

        p = _dc_params()
        with pytest.raises(ValueError):
            simulate_fixture("STRONG", "WEAK", p, n=MIN_N_SIMULATIONS - 1, seed=1)


class TestSimulatePathway:
    """R5: empate 90' → prórroga (λ×1/3) → penales; reparto del camino."""

    def test_sim_reparto_camino_suma_uno(self):
        """p_reg + p_et + p_pens = 1 y todos ≥ 0."""
        from src.simulation.match_sim import simulate_fixture

        p = _dc_params()
        r = simulate_fixture("MID", "MID2", p, n=8000, seed=5, _allow_small_n=True)
        assert r.p_reg + r.p_et + r.p_pens == pytest.approx(1.0)
        assert r.p_reg > 0 and r.p_et > 0  # equipos parejos → habrá prórrogas
        assert min(r.p_reg, r.p_et, r.p_pens) >= 0.0

    def test_sim_empate_resuelve_ganador(self):
        """Ningún empate sobrevive en el resultado del cruce (siempre hay ganador)."""
        from src.simulation.match_sim import simulate_fixture

        p = _dc_params()
        r = simulate_fixture("MID", "MID2", p, n=6000, seed=9, _allow_small_n=True)
        # p_home + p_away = 1 exacto (no queda masa de empate)
        assert r.p_home + r.p_away == pytest.approx(1.0)

    def test_sim_dead_rubber_desplaza(self):
        """Con dead-rubber: E[goles] sube y P(favorito) baja vs baseline (integra R3)."""
        from src.models.dead_rubber import DeadRubber
        from src.simulation.match_sim import simulate_fixture

        p = _dc_params()
        base = simulate_fixture("STRONG", "WEAK", p, n=20000, seed=11)
        damp = simulate_fixture("STRONG", "WEAK", p, n=20000, seed=11,
                                dead_rubber=DeadRubber())
        assert damp.e_goals > base.e_goals          # más abierto
        assert damp.p_home_reg < base.p_home_reg    # ventaja del favorito diluida


class TestSimArtifact:
    """R6: persistencia del resultado agregado."""

    def test_sim_artifact_schema(self, tmp_path: Path):
        """write_sim_result escribe un CSV con esquema estable y round-trip de claves."""
        from src.simulation.match_sim import simulate_fixture, write_sim_result

        p = _dc_params()
        r = simulate_fixture("STRONG", "WEAK", p, n=4000, seed=2, _allow_small_n=True)
        out = tmp_path / "final_sim.csv"
        path = write_sim_result(r, out)
        assert path == out and out.is_file()
        text = out.read_text(encoding="utf-8")
        header = text.splitlines()[0].split(",")
        for col in ("home", "away", "p_home", "p_away", "p_reg", "p_et", "p_pens",
                    "modal_home", "modal_away", "e_goals", "n", "seed"):
            assert col in header, f"falta columna {col!r} en {header}"

    def test_sim_artifact_solo_bajo_data(self, tmp_path: Path):
        """assert_under_data acepta rutas bajo data/ y rechaza fuera (guard R6)."""
        from src.simulation.match_sim import assert_under_data

        assert_under_data(tmp_path / "data" / "predictions" / "x.csv", root=tmp_path)
        with pytest.raises(ValueError):
            assert_under_data(tmp_path / "etc" / "x.csv", root=tmp_path)


# ---------------------------------------------------------------------------
# R1 — Fixtures Final (r2) + 3er puesto (r3p)
# ---------------------------------------------------------------------------

def _ko(round_ordinal, stage, hn, an, hc, ac, *, date, is_third_place=False,
        hg=None, ag=None, finished=False):
    from src.ingestion.fotmob_ko import KoMatch
    return KoMatch(
        round_ordinal=round_ordinal, stage=stage, home_name=hn, away_name=an,
        home_code=hc, away_code=ac, home_goals=hg, away_goals=ag, match_id="0",
        slug="", page_url="", utc_time=f"{date}T19:00:00Z", date=date,
        finished=finished, started=finished, is_third_place=is_third_place,
    )


class TestFixturesFinal3P:
    """R1: writer emite r2_fixtures.csv (Final) y r3p_fixtures.csv (3er puesto)."""

    def test_write_final_fixture_r2(self, tmp_path: Path):
        from src.ingestion.fotmob_ko import write_ko_fixtures
        fin = _ko(5, "Final", "France", "Argentina", "FRA", "ARG", date="2026-07-19")
        written = write_ko_fixtures([fin], tmp_path)
        assert "Final" in written
        r2 = (tmp_path / "r2_fixtures.csv").read_text(encoding="utf-8").splitlines()
        assert r2[0] == "draw_order,date,stage,home_code,away_code,source"
        assert r2[1] == "1,2026-07-19,Final,FRA,ARG,fotmob_official"

    def test_write_r3p_fixture(self, tmp_path: Path):
        from src.ingestion.fotmob_ko import write_ko_fixtures
        tp = _ko(5, "3P", "Spain", "England", "ESP", "ENG",
                 date="2026-07-18", is_third_place=True)
        written = write_ko_fixtures([tp], tmp_path)
        assert "3P" in written
        r3p = (tmp_path / "r3p_fixtures.csv").read_text(encoding="utf-8").splitlines()
        assert r3p[0] == "draw_order,date,stage,home_code,away_code,source"
        assert r3p[1] == "1,2026-07-18,3P,ESP,ENG,fotmob_official"

    def test_r2_r3p_no_se_contaminan(self, tmp_path: Path):
        """El 3er puesto NO entra en r2; la Final NO entra en r3p."""
        from src.ingestion.fotmob_ko import write_ko_fixtures
        fin = _ko(5, "Final", "France", "Argentina", "FRA", "ARG", date="2026-07-19")
        tp = _ko(5, "3P", "Spain", "England", "ESP", "ENG",
                 date="2026-07-18", is_third_place=True)
        write_ko_fixtures([fin, tp], tmp_path)
        r2 = (tmp_path / "r2_fixtures.csv").read_text(encoding="utf-8").splitlines()
        r3p = (tmp_path / "r3p_fixtures.csv").read_text(encoding="utf-8").splitlines()
        assert len(r2) == 2 and "FRA,ARG" in r2[1]
        assert len(r3p) == 2 and "ESP,ENG" in r3p[1]

    def test_tbd_omitido_final(self, tmp_path: Path):
        """Final con un código TBD → r2 sólo header (no inventa)."""
        from src.ingestion.fotmob_ko import write_ko_fixtures
        fin = _ko(5, "Final", "Winner SF1", "Winner SF2", "FRA", None, date="2026-07-19")
        write_ko_fixtures([fin], tmp_path)
        r2 = (tmp_path / "r2_fixtures.csv").read_text(encoding="utf-8").splitlines()
        assert len(r2) == 1  # sólo header

    def test_fixtures_previos_intactos(self, tmp_path: Path):
        """Bracket mixto: r16/r8/r4 siguen escribiéndose (no-regresión)."""
        from src.ingestion.fotmob_ko import write_ko_fixtures
        bracket = [
            _ko(2, "R16", "A", "B", "FRA", "ESP", date="2026-07-04"),
            _ko(3, "QF", "C", "D", "ENG", "ARG", date="2026-07-09"),
            _ko(4, "SF", "E", "F", "FRA", "ESP", date="2026-07-14"),
            _ko(5, "Final", "G", "H", "FRA", "ARG", date="2026-07-19"),
            _ko(5, "3P", "I", "J", "ESP", "ENG", date="2026-07-18", is_third_place=True),
        ]
        written = write_ko_fixtures(bracket, tmp_path)
        for stage, fname in [("R16", "r16_fixtures.csv"), ("QF", "r8_fixtures.csv"),
                             ("SF", "r4_fixtures.csv"), ("Final", "r2_fixtures.csv"),
                             ("3P", "r3p_fixtures.csv")]:
            assert stage in written
            lines = (tmp_path / fname).read_text(encoding="utf-8").splitlines()
            assert len(lines) == 2, f"{fname} debería tener 1 fila"


# ---------------------------------------------------------------------------
# R2 — Detección del 3er puesto en la estructura fotmob
# ---------------------------------------------------------------------------

def _round(matchups):
    return {"matchups": matchups}


def _matchup(hn, an, *, hs=None, as_=None, finished=False, name=None, pageurl=None):
    m = {
        "home": {"name": hn, "score": hs},
        "away": {"name": an, "score": as_},
        "status": {"finished": finished, "started": finished, "utcTime": "2026-07-18T19:00:00Z"},
        "pageUrl": pageurl or f"/matches/{hn}-vs-{an}/x#1",
    }
    if name is not None:
        m["name"] = name
    return {"matches": [m]}


def _next_data(rounds):
    return {"props": {"pageProps": {"playoff": {"rounds": rounds}}}}


class TestDeteccion3P:
    """R2: distingue el 3er puesto de la Final dentro de la misma ronda."""

    def test_komatch_is_third_place_default_false(self):
        """Retrocompat: KoMatch sin el flag → is_third_place False."""
        from src.ingestion.fotmob_ko import KoMatch
        km = KoMatch(round_ordinal=5, stage="Final", home_name="a", away_name="b",
                     home_code="FRA", away_code="ARG", home_goals=None, away_goals=None,
                     match_id="0", slug="", page_url="", utc_time="", date="2026-07-19",
                     finished=False, started=False)
        assert km.is_third_place is False

    def test_detecta_3p_por_etiqueta(self):
        """Etiqueta fotmob '3rd place' → matchup marcado is_third_place, stage '3P'."""
        from src.ingestion.fotmob_ko import parse_playoff_bracket
        rounds = [
            _round([]), _round([]), _round([]), _round([]),  # R32..SF vacíos
            _round([
                _matchup("Spain", "England", name="3rd Place Play-off"),
                _matchup("France", "Argentina", name="Final"),
            ]),
        ]
        bracket = parse_playoff_bracket(_next_data(rounds))
        tp = [k for k in bracket if k.is_third_place]
        fin = [k for k in bracket if not k.is_third_place and k.round_ordinal == 5]
        assert len(tp) == 1 and tp[0].stage == "3P"
        assert {tp[0].home_code, tp[0].away_code} == {"ESP", "ENG"}
        assert len(fin) == 1 and fin[0].stage == "Final"
        assert {fin[0].home_code, fin[0].away_code} == {"FRA", "ARG"}

    def test_detecta_3p_por_perdedores_sf(self):
        """Sin etiqueta: el cruce de los dos perdedores de semis → 3P."""
        from src.ingestion.fotmob_ko import parse_playoff_bracket
        # SF: FRA vence ESP (2-1), ARG vence ENG (1-0) → perdedores ESP, ENG.
        sf = _round([
            _matchup("France", "Spain", hs=2, as_=1, finished=True),
            _matchup("Argentina", "England", hs=1, as_=0, finished=True),
        ])
        last = _round([
            _matchup("Spain", "England"),      # perdedores → 3P
            _matchup("France", "Argentina"),   # ganadores → Final
        ])
        rounds = [_round([]), _round([]), _round([]), sf, last]
        bracket = parse_playoff_bracket(_next_data(rounds))
        tp = [k for k in bracket if k.is_third_place]
        assert len(tp) == 1
        assert {tp[0].home_code, tp[0].away_code} == {"ESP", "ENG"}
        assert tp[0].stage == "3P"

    def test_sf_sin_marcador_no_inventa_3p(self):
        """Sin etiqueta y semis sin marcador → no se marca ningún 3P (conservador)."""
        from src.ingestion.fotmob_ko import parse_playoff_bracket
        sf = _round([
            _matchup("France", "Spain"),       # sin finished/score
            _matchup("Argentina", "England"),
        ])
        last = _round([
            _matchup("Spain", "England"),
            _matchup("France", "Argentina"),
        ])
        rounds = [_round([]), _round([]), _round([]), sf, last]
        bracket = parse_playoff_bracket(_next_data(rounds))
        assert not any(k.is_third_place for k in bracket)


class TestSynthesize3P:
    """R2: cuando fotmob OMITE el 3er puesto del árbol, se sintetiza de los perdedores SF."""

    def test_synthesize_3p_desde_perdedores(self):
        """Bracket sin 3P + Final único → sintetiza FRA-ENG (perdedores) el día previo."""
        from src.ingestion.fotmob_ko import synthesize_third_place
        bracket = [
            _ko(4, "SF", "France", "Spain", "FRA", "ESP", date="2026-07-14",
                hg=0, ag=1, finished=True),      # ESP gana → FRA perdedor
            _ko(4, "SF", "England", "Argentina", "ENG", "ARG", date="2026-07-15",
                hg=1, ag=2, finished=True),       # ARG gana → ENG perdedor
            _ko(5, "Final", "Spain", "Argentina", "ESP", "ARG", date="2026-07-19"),
        ]
        tp = synthesize_third_place(bracket)
        assert tp is not None
        assert tp.is_third_place and tp.stage == "3P"
        assert (tp.home_code, tp.away_code) == ("FRA", "ENG")
        assert tp.date == "2026-07-18"  # día previo a la Final
        assert tp.finished is False

    def test_synthesize_none_si_ya_existe_3p(self):
        """Si el bracket ya trae un 3P (etiqueta), no se sintetiza otro."""
        from src.ingestion.fotmob_ko import synthesize_third_place
        bracket = [
            _ko(5, "Final", "Spain", "Argentina", "ESP", "ARG", date="2026-07-19"),
            _ko(5, "3P", "France", "England", "FRA", "ENG", date="2026-07-18",
                is_third_place=True),
        ]
        assert synthesize_third_place(bracket) is None

    def test_synthesize_none_si_sf_sin_marcador(self):
        """Sin perdedores resolubles (SF sin marcador) → no se inventa nada."""
        from src.ingestion.fotmob_ko import synthesize_third_place
        bracket = [
            _ko(4, "SF", "France", "Spain", "FRA", "ESP", date="2026-07-14"),
            _ko(4, "SF", "England", "Argentina", "ENG", "ARG", date="2026-07-15"),
            _ko(5, "Final", "TBD", "TBD", None, None, date="2026-07-19"),
        ]
        assert synthesize_third_place(bracket) is None

    def test_dead_rubber_acotado(self):
        """delta∈[0,1] y kappa≥1; fuera de rango → ValueError."""
        from src.models.dead_rubber import DeadRubber

        with pytest.raises(ValueError):
            DeadRubber(delta=1.5, kappa=1.1)
        with pytest.raises(ValueError):
            DeadRubber(delta=0.4, kappa=0.5)
