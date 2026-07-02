"""tests/test_form_xg.py — Feature 26: forma_xg, R1–R6.

Trazabilidad (tasks.md):
| R1 | test_ventana_lleva_xg_y_fallback_null                                    |
| R2 | test_metrica_usa_xg_donde_hay_y_gol_donde_no, test_pesos_recencia_se_conservan |
| R3 | test_use_xg_false_equivale_f16_1e9, test_ventana_sin_xg_equivale_goles  |
| R4 | test_form_xg_flag_en_predict, test_form_xg_flag_en_backtest,
|    | test_form_xg_flag_en_simulate, test_form_xg_default_es_false,
|    | test_subcomandos_exactos_intactos                                        |
| R5 | test_backtest_forma_goles_vs_xg_reproducible                            |
| R6 | transversal (offline, as_of inyectado, sin libs nuevas)                 |

100% offline — fixtures sinteticos en memoria, sin red, sin reloj (as_of inyectado).
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.form.config import DEFAULT_FORM_CONFIG, WC2026_START_DATE, WC_TOURNAMENT
from src.form.factor import make_form_factor_fn, make_form_factory
from src.form.metrics import team_form
from src.form.window import MatchInWindow, build_window, index_matches_by_team


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silver(rows: list[dict]) -> pd.DataFrame:
    """Construye un DataFrame de silver minimo desde una lista de dicts."""
    defaults: dict = {
        "match_id": "T",
        "date": "2026-01-01",
        "home_code": "AAA",
        "away_code": "BBB",
        "home_goals": 1,
        "away_goals": 0,
        "tournament": "Friendly",
        "neutral": False,
        # xG columnas opcionales — no presentes en defaults (prueba de fallback)
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _make_silver_with_xg(rows: list[dict]) -> pd.DataFrame:
    """Construye un DataFrame de silver con columnas home_xg/away_xg (F23)."""
    defaults: dict = {
        "match_id": "T",
        "date": "2026-01-01",
        "home_code": "AAA",
        "away_code": "BBB",
        "home_goals": 1,
        "away_goals": 0,
        "tournament": "Friendly",
        "neutral": False,
        "home_xg": float("nan"),
        "away_xg": float("nan"),
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


# ---------------------------------------------------------------------------
# R1 — La ventana lleva xg_for/xg_against con fallback null
# ---------------------------------------------------------------------------

class TestVentanaXgR1:
    """R1: build_window/index_matches_by_team popula xg_for/xg_against correctamente."""

    def test_ventana_lleva_xg_y_fallback_null(self):
        """R1: partidos con xG → xg_for/xg_against poblados; sin xG → None."""
        team = "ARG"
        rows = [
            # Partido WC con xG
            {
                "home_code": team,
                "away_code": "BRA",
                "date": "2026-06-15",
                "home_goals": 2,
                "away_goals": 1,
                "tournament": WC_TOURNAMENT,
                "home_xg": 1.8,
                "away_xg": 0.7,
            },
            # Partido pre-WC sin xG (NaN)
            {
                "home_code": team,
                "away_code": "CHI",
                "date": "2026-05-01",
                "home_goals": 1,
                "away_goals": 0,
                "tournament": "Friendly",
                "home_xg": float("nan"),
                "away_xg": float("nan"),
            },
            # Partido pre-WC sin columnas xG en absoluto (fixture sin xG)
        ]
        matches = _make_silver_with_xg(rows)
        window = build_window(matches, team, as_of="2026-07-01")

        # Hay exactamente 2 partidos en la ventana
        assert len(window) == 2

        # Buscar el partido WC (el mas reciente)
        wc_match = next(m for m in window if m.is_group_wc)
        pre_match = next(m for m in window if not m.is_group_wc)

        # Partido WC: xg_for=1.8, xg_against=0.7 (perspectiva ARG como local)
        assert wc_match.xg_for is not None
        assert wc_match.xg_against is not None
        assert abs(wc_match.xg_for - 1.8) < 1e-9
        assert abs(wc_match.xg_against - 0.7) < 1e-9

        # Partido pre-WC: xG NaN → None
        assert pre_match.xg_for is None
        assert pre_match.xg_against is None

    def test_ventana_xg_perspectiva_visitante(self):
        """R1: cuando el equipo juega como visitante, xg_for/xg_against se invierten."""
        team = "BRA"
        rows = [
            {
                "home_code": "ARG",
                "away_code": team,
                "date": "2026-06-15",
                "home_goals": 1,
                "away_goals": 2,
                "tournament": WC_TOURNAMENT,
                "home_xg": 0.9,
                "away_xg": 2.3,
            },
        ]
        matches = _make_silver_with_xg(rows)
        window = build_window(matches, team, as_of="2026-07-01")

        assert len(window) == 1
        m = window[0]
        # BRA es visitante: xg_for = away_xg = 2.3, xg_against = home_xg = 0.9
        assert m.xg_for is not None
        assert m.xg_against is not None
        assert abs(m.xg_for - 2.3) < 1e-9
        assert abs(m.xg_against - 0.9) < 1e-9

    def test_silver_sin_columnas_xg_da_none(self):
        """R1/R6: silver sin columnas home_xg/away_xg → xg_for/xg_against=None (degradacion)."""
        team = "ARG"
        rows = [
            {
                "home_code": team,
                "away_code": "BRA",
                "date": "2026-06-15",
                "home_goals": 2,
                "away_goals": 1,
                "tournament": WC_TOURNAMENT,
            },
        ]
        # Sin columnas xG en el DataFrame
        matches = _make_silver(rows)
        window = build_window(matches, team, as_of="2026-07-01")

        assert len(window) == 1
        m = window[0]
        assert m.xg_for is None
        assert m.xg_against is None


# ---------------------------------------------------------------------------
# R2 — Metrica usa xG donde hay y gol donde no (mezcla por partido)
# ---------------------------------------------------------------------------

class TestMetricaXgR2:
    """R2: team_form(use_xg=True) usa xG-diff donde hay y gol-diff donde no."""

    def test_metrica_usa_xg_donde_hay_y_gol_donde_no(self):
        """R2: oraculo con mezcla xG/gol por partido; resultado determinista."""
        # Match A (mas antiguo, i=0): gf=2, ga=0, xg_for=1.5, xg_against=0.3
        # Match B (mas reciente, i=1): gf=1, ga=1, xg=None (fallback a goles)
        window = [
            MatchInWindow(
                date="2026-06-14",
                is_group_wc=True,
                gf=2,
                ga=0,
                opp_code="BRA",
                result="W",
                xg_for=1.5,
                xg_against=0.3,
            ),
            MatchInWindow(
                date="2026-06-18",
                is_group_wc=True,
                gf=1,
                ga=1,
                opp_code="FRA",
                result="D",
                xg_for=None,
                xg_against=None,
            ),
        ]

        # Calculo manual del oraculo (decay=0.85, tier=2.0 WC, q=1.0 sin elo)
        # n=2, rank[0]=1, rank[1]=0
        # w[0] = 0.85^1 * 2.0 * 1.0 = 1.7
        # w[1] = 0.85^0 * 2.0 * 1.0 = 2.0
        # Con use_xg=True:
        #   signal[0] = xg_for - xg_against = 1.5 - 0.3 = 1.2 (xG disponible)
        #   signal[1] = gf - ga = 1 - 1 = 0.0 (fallback)
        # gd_sum = 1.7 * 1.2 + 2.0 * 0.0 = 2.04
        # total_w = 1.7 + 2.0 = 3.7
        # gd_w = 2.04 / 3.7 ≈ 0.55135...

        metrics_xg = team_form(window, {}, use_xg=True)
        expected_gd_w = 2.04 / 3.7

        assert abs(metrics_xg.gd_w - expected_gd_w) < 1e-9, (
            f"gd_w esperado {expected_gd_w:.9f}, obtenido {metrics_xg.gd_w:.9f}"
        )

    def test_pesos_recencia_se_conservan(self):
        """R2: con use_xg=True los pesos (decay, tier, q) no cambian — solo la senal."""
        window = [
            MatchInWindow(
                date="2026-06-14",
                is_group_wc=True,
                gf=2,
                ga=0,
                opp_code="BRA",
                result="W",
                xg_for=1.5,
                xg_against=0.3,
            ),
            MatchInWindow(
                date="2026-06-18",
                is_group_wc=True,
                gf=1,
                ga=1,
                opp_code="FRA",
                result="D",
                xg_for=None,
                xg_against=None,
            ),
        ]

        m_gol = team_form(window, {}, use_xg=False)
        m_xg = team_form(window, {}, use_xg=True)

        # gf_w, ga_w, ppg_w deben ser identicos (solo la senal de gd cambia)
        assert abs(m_gol.gf_w - m_xg.gf_w) < 1e-9, "gf_w debe ser identico"
        assert abs(m_gol.ga_w - m_xg.ga_w) < 1e-9, "ga_w debe ser identico"
        assert abs(m_gol.ppg_w - m_xg.ppg_w) < 1e-9, "ppg_w debe ser identico"
        assert m_gol.streak == m_xg.streak, "streak debe ser identico"

        # gd_w debe diferir (xG != gol-diff en este fixture)
        assert abs(m_gol.gd_w - m_xg.gd_w) > 1e-6, (
            f"gd_w debe diferir: gol={m_gol.gd_w:.6f}, xg={m_xg.gd_w:.6f}"
        )


# ---------------------------------------------------------------------------
# R3 — Activacion + no-regresion exacta
# ---------------------------------------------------------------------------

class TestNoRegresionR3:
    """R3: use_xg=False -> identico a F16; ventana sin xG + use_xg=True -> identico a goles."""

    def test_use_xg_false_equivale_f16_1e9(self):
        """R3: use_xg=False con ventana que tiene xG → identico a F16 (tol 1e-9)."""
        # Ventana con xG disponible; use_xg=False debe ignorarlo
        window = [
            MatchInWindow(
                date="2026-06-14",
                is_group_wc=True,
                gf=2,
                ga=0,
                opp_code="BRA",
                result="W",
                xg_for=1.5,
                xg_against=0.3,
            ),
            MatchInWindow(
                date="2026-06-18",
                is_group_wc=False,
                gf=1,
                ga=1,
                opp_code="CHI",
                result="D",
                xg_for=0.8,
                xg_against=0.9,
            ),
        ]

        # F16 reference: construir identica ventana sin xG (xg=None)
        window_f16 = [
            MatchInWindow(
                date=m.date,
                is_group_wc=m.is_group_wc,
                gf=m.gf,
                ga=m.ga,
                opp_code=m.opp_code,
                result=m.result,
                # sin xg_for / xg_against (defaults None)
            )
            for m in window
        ]

        m_f16 = team_form(window_f16, {})          # F16 exact (use_xg=False implícito)
        m_off = team_form(window, {}, use_xg=False) # F26 con use_xg=False

        assert abs(m_f16.gd_w - m_off.gd_w) < 1e-9, (
            f"use_xg=False debe ser identico a F16: f16={m_f16.gd_w:.12f}, off={m_off.gd_w:.12f}"
        )
        assert abs(m_f16.gf_w - m_off.gf_w) < 1e-9
        assert abs(m_f16.ga_w - m_off.ga_w) < 1e-9
        assert abs(m_f16.ppg_w - m_off.ppg_w) < 1e-9

    def test_ventana_sin_xg_equivale_goles(self):
        """R3: ventana sin ningun xG + use_xg=True → identico a use_xg=False."""
        window = [
            MatchInWindow(
                date="2026-06-14",
                is_group_wc=True,
                gf=3,
                ga=1,
                opp_code="BRA",
                result="W",
                xg_for=None,
                xg_against=None,
            ),
            MatchInWindow(
                date="2026-06-18",
                is_group_wc=False,
                gf=0,
                ga=2,
                opp_code="CHI",
                result="L",
                xg_for=None,
                xg_against=None,
            ),
        ]

        m_off = team_form(window, {}, use_xg=False)
        m_on = team_form(window, {}, use_xg=True)

        assert abs(m_off.gd_w - m_on.gd_w) < 1e-9, (
            f"Ventana sin xG: use_xg=True debe ser identico a use_xg=False; "
            f"off={m_off.gd_w:.12f}, on={m_on.gd_w:.12f}"
        )

    def test_factor_fn_use_xg_false_identico_f16(self):
        """R3: make_form_factor_fn con use_xg=False produce factores identicos a F16 (tol 1e-9)."""
        teams = ["ARG", "BRA", "FRA"]
        rows = [
            {
                "home_code": "ARG",
                "away_code": "BRA",
                "date": "2026-06-15",
                "home_goals": 2,
                "away_goals": 1,
                "tournament": WC_TOURNAMENT,
                "home_xg": 1.8,
                "away_xg": 0.6,
            },
            {
                "home_code": "FRA",
                "away_code": "ARG",
                "date": "2026-06-19",
                "home_goals": 1,
                "away_goals": 1,
                "tournament": WC_TOURNAMENT,
                "home_xg": 1.2,
                "away_xg": 1.1,
            },
        ]
        matches_xg = _make_silver_with_xg(rows)
        matches_no_xg = _make_silver(rows)  # sin columnas xG

        gamma = 0.3
        as_of = "2026-07-01"

        # F16: silver sin xG, use_xg=False (default)
        fn_f16 = make_form_factor_fn(matches_no_xg, as_of, None, gamma, teams)
        # F26: silver con xG, use_xg=False
        fn_off = make_form_factor_fn(matches_xg, as_of, None, gamma, teams, use_xg=False)

        for home, away in [("ARG", "BRA"), ("FRA", "ARG"), ("BRA", "FRA")]:
            mh_f16, ma_f16 = fn_f16(home, away)
            mh_off, ma_off = fn_off(home, away)
            assert abs(mh_f16 - mh_off) < 1e-9, (
                f"{home} vs {away}: use_xg=False debe ser F16; "
                f"f16={mh_f16:.12f}, off={mh_off:.12f}"
            )
            assert abs(ma_f16 - ma_off) < 1e-9


# ---------------------------------------------------------------------------
# R4 — CLI flag --form-xg en predict, backtest, simulate
# ---------------------------------------------------------------------------

class TestCliFormXgFlagR4:
    """R4: --form-xg registrado en predict, backtest y simulate; default False."""

    def test_form_xg_flag_en_predict(self):
        """R4: --form-xg registrado en predict."""
        import argparse
        import src.cli as cli
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        predict_parser = sub.choices["predict"]
        help_text = predict_parser.format_help()
        assert "form-xg" in help_text, "predict debe documentar --form-xg"

    def test_form_xg_flag_en_backtest(self):
        """R4: --form-xg registrado en backtest."""
        import argparse
        import src.cli as cli
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        backtest_parser = sub.choices["backtest"]
        help_text = backtest_parser.format_help()
        assert "form-xg" in help_text, "backtest debe documentar --form-xg"

    def test_form_xg_flag_en_simulate(self):
        """R4: --form-xg registrado en simulate."""
        import argparse
        import src.cli as cli
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        simulate_parser = sub.choices["simulate"]
        help_text = simulate_parser.format_help()
        assert "form-xg" in help_text, "simulate debe documentar --form-xg"

    def test_form_xg_default_es_false(self):
        """R4: --form-xg default=False en predict/backtest/simulate."""
        import src.cli as cli
        parser = cli.build_parser()
        for subcmd in ("predict ARG BRA", "backtest", "simulate"):
            args = parser.parse_args(subcmd.split())
            assert hasattr(args, "form_xg"), f"{subcmd} debe tener atributo form_xg"
            assert args.form_xg is False, f"{subcmd}: form_xg default debe ser False"

    def test_form_xg_store_true_activa_flag(self):
        """R4: --form-xg store_true → args.form_xg=True cuando se pasa."""
        import src.cli as cli
        parser = cli.build_parser()
        args = parser.parse_args(["predict", "ARG", "BRA", "--form-xg"])
        assert args.form_xg is True

    def test_subcomandos_exactos_intactos(self):
        """R4: --form-xg NO añade subcomandos nuevos — set exacto de 18 intacto."""
        import argparse
        import src.cli as cli
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        expected = {
            "ingest-public",
            "build-features",
            "train",
            "predict",
            "schedule",
            "markets",
            "backtest",
            "predict-log",
            "evaluate",
            "ingest-goalscorers",
            "scorers",
            "simulate",
            "ingest-elo",
            "ingest-wiki-stats",
            "ingest-roster",
            "ingest-fotmob-stats",
            "corners",
            "count-market",
        }
        assert set(sub.choices) == expected, (
            f"Subcomandos inesperados: {set(sub.choices) - expected} o faltantes: "
            f"{expected - set(sub.choices)}"
        )
        assert len(sub.choices) == 18, f"Esperados 18, encontrados {len(sub.choices)}"

    def test_form_xg_no_en_schedule(self):
        """R4: subcomandos distintos de predict/backtest/simulate no tienen form_xg."""
        import src.cli as cli
        parser = cli.build_parser()
        for subcmd in ("schedule", "evaluate"):
            args = parser.parse_args([subcmd])
            assert not hasattr(args, "form_xg"), (
                f"{subcmd} NO debe exponer form_xg (Feature 26 solo aplica a "
                "predict/backtest/simulate)"
            )


# ---------------------------------------------------------------------------
# R5 — Medicion: determinismo y comparabilidad goles vs xG
# ---------------------------------------------------------------------------

class TestBtFormaXgR5:
    """R5: forma-goles vs forma-xG reproducible y comparables offline."""

    def test_backtest_forma_goles_vs_xg_reproducible(self):
        """R5: con mismo silver, gamma y as_of → resultados deterministas y distintos."""
        teams = ["ARG", "BRA", "FRA", "GER"]
        rows = [
            # ARG vs BRA: xG disponible
            {
                "home_code": "ARG",
                "away_code": "BRA",
                "date": "2026-06-15",
                "home_goals": 3,
                "away_goals": 0,
                "tournament": WC_TOURNAMENT,
                "home_xg": 1.2,
                "away_xg": 0.4,
            },
            # FRA vs GER: xG disponible
            {
                "home_code": "FRA",
                "away_code": "GER",
                "date": "2026-06-16",
                "home_goals": 1,
                "away_goals": 2,
                "tournament": WC_TOURNAMENT,
                "home_xg": 1.5,
                "away_xg": 1.0,
            },
            # ARG vs FRA: sin xG
            {
                "home_code": "ARG",
                "away_code": "FRA",
                "date": "2026-05-01",
                "home_goals": 1,
                "away_goals": 0,
                "tournament": "Friendly",
                "home_xg": float("nan"),
                "away_xg": float("nan"),
            },
        ]
        matches = _make_silver_with_xg(rows)
        gamma = 0.25
        as_of = "2026-07-01"

        # Dos llamadas con use_xg=False → identicas (determinismo)
        fn_gol_1 = make_form_factor_fn(matches, as_of, None, gamma, teams, use_xg=False)
        fn_gol_2 = make_form_factor_fn(matches, as_of, None, gamma, teams, use_xg=False)

        for home, away in [("ARG", "BRA"), ("FRA", "GER")]:
            mh1, ma1 = fn_gol_1(home, away)
            mh2, ma2 = fn_gol_2(home, away)
            assert abs(mh1 - mh2) < 1e-12, "Determinismo: goles run1 != run2"
            assert abs(ma1 - ma2) < 1e-12

        # Dos llamadas con use_xg=True → identicas (determinismo)
        fn_xg_1 = make_form_factor_fn(matches, as_of, None, gamma, teams, use_xg=True)
        fn_xg_2 = make_form_factor_fn(matches, as_of, None, gamma, teams, use_xg=True)

        for home, away in [("ARG", "BRA"), ("FRA", "GER")]:
            mh1, ma1 = fn_xg_1(home, away)
            mh2, ma2 = fn_xg_2(home, away)
            assert abs(mh1 - mh2) < 1e-12, "Determinismo: xg run1 != run2"
            assert abs(ma1 - ma2) < 1e-12

        # Goles vs xG → deben diferir cuando hay xG en la ventana
        # (ARG tiene xG en su partido WC con BRA; los factores deben diferir)
        mh_gol, ma_gol = fn_gol_1("ARG", "BRA")
        mh_xg, _ = fn_xg_1("ARG", "BRA")
        # Con xG 1.2-0.4=0.8 vs goles 3-0=3, la señal de ARG cambia → factor diferente
        assert abs(mh_gol - mh_xg) > 1e-6, (
            f"Con xG disponible, factor ARG debe diferir: gol={mh_gol:.6f}, xg={mh_xg:.6f}"
        )

    def test_factory_use_xg_determinista(self):
        """R5: make_form_factory con use_xg=True es determinista por as_of."""
        teams = ["ARG", "BRA"]
        rows = [
            {
                "home_code": "ARG",
                "away_code": "BRA",
                "date": "2026-06-15",
                "home_goals": 2,
                "away_goals": 1,
                "tournament": WC_TOURNAMENT,
                "home_xg": 1.5,
                "away_xg": 0.8,
            },
        ]
        matches = _make_silver_with_xg(rows)
        gamma = 0.3

        factory = make_form_factory(matches, None, gamma, teams, use_xg=True)
        as_of = "2026-07-01"
        fn1 = factory(as_of)
        fn2 = factory(as_of)

        mh1, ma1 = fn1("ARG", "BRA")
        mh2, ma2 = fn2("ARG", "BRA")
        assert abs(mh1 - mh2) < 1e-12
        assert abs(ma1 - ma2) < 1e-12

    def test_factory_gamma0_es_identidad_con_use_xg(self):
        """R5/R3: gamma=0 → identity factory independientemente de use_xg (fast-path, tol 1e-9)."""
        teams = ["ARG", "BRA"]
        rows = [
            {
                "home_code": "ARG",
                "away_code": "BRA",
                "date": "2026-06-15",
                "home_goals": 2,
                "away_goals": 1,
                "tournament": WC_TOURNAMENT,
                "home_xg": 1.5,
                "away_xg": 0.8,
            },
        ]
        matches = _make_silver_with_xg(rows)

        factory = make_form_factory(matches, None, 0.0, teams, use_xg=True)
        fn = factory("2026-07-01")
        mh, ma = fn("ARG", "BRA")
        assert abs(mh - 1.0) < 1e-9
        assert abs(ma - 1.0) < 1e-9
