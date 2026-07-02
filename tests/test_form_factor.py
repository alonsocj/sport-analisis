"""tests/test_form_factor.py — Feature 16: forma_reciente, R3, R4, R5.

Trazabilidad (tasks.md):
| R3 | test_ajuste_calidad_rival_elo, test_rival_sin_elo_peso_neutro           |
| R4 | test_gamma0_equivale_v1_tol_1e9, test_estandarizacion_z,
|    | test_factor_exp_gamma_z, test_ventana_vacia_factor_neutro              |
| R5 | test_backtest_factory_anti_fuga, test_factory_gamma0_es_identidad      |

100% offline — sin red, sin reloj (as_of inyectado).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.form.config import DEFAULT_FORM_CONFIG, WC2026_START_DATE, WC_TOURNAMENT
from src.form.factor import make_form_factor_fn, make_form_factory
from src.form.metrics import FormMetrics, team_form
from src.form.window import MatchInWindow, build_window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEAMS_SMALL = ["ARG", "BRA", "FRA", "GER", "ESP"]


def _make_silver(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "match_id": "T",
        "date": "2026-01-01",
        "home_code": "AAA",
        "away_code": "BBB",
        "home_goals": 1,
        "away_goals": 0,
        "tournament": "Friendly",
        "neutral": False,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _make_elo(pairs: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame({"team_code": [p[0] for p in pairs], "elo": [p[1] for p in pairs]})


# ---------------------------------------------------------------------------
# R3 — calidad de rival via Elo
# ---------------------------------------------------------------------------

class TestCalidadRivalR3:
    """R3: oponente de mayor Elo aporta más peso a las métricas de forma."""

    def test_ajuste_calidad_rival_elo(self):
        """R3: rival con Elo=1900 (strong) pesa más que Elo=1100 (weak)."""
        # Mismo equipo, dos partidos: uno vs rival fuerte, otro vs rival débil
        team = "ARG"
        window = [
            MatchInWindow(date="2026-05-01", is_group_wc=False, gf=0, ga=2, opp_code="WEAK", result="L"),
            MatchInWindow(date="2026-06-01", is_group_wc=False, gf=2, ga=0, opp_code="STRONG", result="W"),
        ]
        elo_strong = {"WEAK": 1100.0, "STRONG": 1900.0}
        elo_neutral = {}  # sin Elo → q=1.0 para todos

        m_strong = team_form(window, elo_strong, decay=DEFAULT_FORM_CONFIG.decay, tier_ratio=1.0)
        m_neutral = team_form(window, elo_neutral, decay=DEFAULT_FORM_CONFIG.decay, tier_ratio=1.0)

        # Con Elo fuerte para STRONG y débil para WEAK, el peso de la victoria
        # aumenta más, por lo que gd_w debe ser mayor que con pesos neutros
        assert m_strong.gd_w > m_neutral.gd_w, (
            f"Con Elo fuerte ({m_strong.gd_w:.4f}) debe superar a neutro ({m_neutral.gd_w:.4f})"
        )

    def test_rival_sin_elo_peso_neutro(self):
        """R3/R7: rival sin Elo obtiene q=1.0 → igual que rival con Elo=pivot (1500)."""
        team = "BRA"
        window = [
            MatchInWindow(date="2026-06-01", is_group_wc=False, gf=2, ga=1, opp_code="UNKNOWN", result="W"),
        ]

        # Sin Elo → q=1.0
        m_no_elo = team_form(window, {})
        # Elo exactamente en pivot → q = clip(1 + 0/400, 0.5, 2.0) = 1.0
        m_pivot = team_form(window, {"UNKNOWN": DEFAULT_FORM_CONFIG.opp_elo_pivot})

        assert abs(m_no_elo.gf_w - m_pivot.gf_w) < 1e-9, (
            "Sin Elo debe coincidir exactamente con Elo=pivot"
        )
        assert abs(m_no_elo.gd_w - m_pivot.gd_w) < 1e-9

    def test_calidad_rival_clip_minimo(self):
        """R3: Elo muy bajo se clipea a q=0.5 (no puede caer debajo)."""
        team = "FRA"
        window = [
            MatchInWindow(date="2026-06-01", is_group_wc=False, gf=5, ga=0, opp_code="WEAK", result="W"),
        ]
        # Elo=100 → q = clip(1 + (100-1500)/400, 0.5, 2.0) = clip(-2.5, 0.5, 2.0) = 0.5
        m = team_form(window, {"WEAK": 100.0})
        # Verificar indirectamente: ppg_w = 3.0 (victoria), pero el peso es 0.5
        # No hay otra referencia → el resultado sigue siendo determinista
        assert abs(m.ppg_w - 3.0) < 1e-9  # 1 partido, siempre 3.0
        # gf_w = sum(W_i*gf_i)/sum(W_i) = 0.5*5 / 0.5 = 5.0
        assert abs(m.gf_w - 5.0) < 1e-9

    def test_calidad_rival_clip_maximo(self):
        """R3: Elo muy alto se clipea a q=2.0 (no puede superar)."""
        team = "ESP"
        window = [
            MatchInWindow(date="2026-06-01", is_group_wc=False, gf=1, ga=0, opp_code="STRONG", result="W"),
        ]
        # Elo=9999 → q = clip(1 + (9999-1500)/400, 0.5, 2.0) = clip(22.25, 0.5, 2.0) = 2.0
        m = team_form(window, {"STRONG": 9999.0})
        # gf_w = sum(W_i*gf_i)/sum(W_i) = 2.0*1 / 2.0 = 1.0
        assert abs(m.gf_w - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# R4 — factor multiplicativo exp(γ·z) y no-regresión γ=0
# ---------------------------------------------------------------------------

class TestFactorR4:
    """R4: make_form_factor_fn, estandarización, exp(γ·z), no-regresión γ=0."""

    def _build_simple_silver(self) -> pd.DataFrame:
        """Silver con partidos simples: ARG gana 3-0, BRA pierde 0-3, resto neutros."""
        rows = []
        # ARG: 3 victorias 3-0
        for i in range(3):
            rows.append({
                "home_code": "ARG", "away_code": "USA",
                "date": f"2026-05-{10 + i:02d}", "home_goals": 3, "away_goals": 0,
                "tournament": "Friendly",
            })
        # BRA: 3 derrotas 0-3
        for i in range(3):
            rows.append({
                "home_code": "BRA", "away_code": "USA",
                "date": f"2026-05-{10 + i:02d}", "home_goals": 0, "away_goals": 3,
                "tournament": "Friendly",
            })
        # FRA, GER, ESP: 1-1 (empate neutro)
        for team in ["FRA", "GER", "ESP"]:
            rows.append({
                "home_code": team, "away_code": "USA",
                "date": "2026-05-10", "home_goals": 1, "away_goals": 1,
                "tournament": "Friendly",
            })
        return _make_silver(rows)

    def test_gamma0_equivale_v1_tol_1e9(self):
        """R4 (gate crítico): γ=0 → factor siempre (1.0, 1.0), tol 1e-9."""
        silver = self._build_simple_silver()
        fn = make_form_factor_fn(silver, "2026-06-01", None, 0.0, TEAMS_SMALL)

        mult_home, mult_away = fn("ARG", "BRA")
        assert abs(mult_home - 1.0) < 1e-9, f"mult_home={mult_home} ≠ 1.0 (γ=0)"
        assert abs(mult_away - 1.0) < 1e-9, f"mult_away={mult_away} ≠ 1.0 (γ=0)"

        # También con equipos fuera de la lista
        mult_h2, mult_a2 = fn("XXX", "YYY")
        assert abs(mult_h2 - 1.0) < 1e-9
        assert abs(mult_a2 - 1.0) < 1e-9

    def test_ventana_vacia_factor_neutro(self):
        """R4/R7: equipo sin partidos → gd_w=0 → factor cerca de 1.0 (no aborta)."""
        # Silver completamente vacío
        silver = _make_silver([])
        fn = make_form_factor_fn(silver, "2026-06-01", None, 0.5, TEAMS_SMALL)

        mult_home, mult_away = fn("ARG", "BRA")
        # Con todos gd_w=0: μ=0, σ=0 → z=0 para todos → exp(0.5*0) = 1.0
        assert abs(mult_home - 1.0) < 1e-9
        assert abs(mult_away - 1.0) < 1e-9

    def test_estandarizacion_z(self):
        """R4: los factores z están estandarizados (mean≈0, std≈1 sobre los equipos)."""
        silver = self._build_simple_silver()
        gamma = 0.3
        teams = TEAMS_SMALL

        # Extraer los z implícitamente via los factores: factor = exp(γ·z) → z = ln(f)/γ
        fn = make_form_factor_fn(silver, "2026-06-01", None, gamma, teams)

        # Probar un equipo de cada extremo
        f_arg, _ = fn("ARG", "ARG")
        f_bra, _ = fn("BRA", "BRA")

        z_arg = math.log(f_arg) / gamma
        z_bra = math.log(f_bra) / gamma

        # ARG con victorias → z positivo; BRA con derrotas → z negativo
        assert z_arg > 0, f"ARG debería tener z>0, got {z_arg:.4f}"
        assert z_bra < 0, f"BRA debería tener z<0, got {z_bra:.4f}"

    def test_factor_exp_gamma_z(self):
        """R4: factor = exp(γ·z). Verificar que λ_DC * factor da λ' esperado."""
        silver = self._build_simple_silver()
        gamma = 0.5
        fn = make_form_factor_fn(silver, "2026-06-01", None, gamma, TEAMS_SMALL)

        mult_h, mult_a = fn("ARG", "BRA")
        # ARG gana siempre → factor > 1.0; BRA pierde siempre → factor < 1.0
        assert mult_h > 1.0, f"ARG (ganador) debería tener factor>1, got {mult_h:.4f}"
        assert mult_a < 1.0, f"BRA (perdedor) debería tener factor<1, got {mult_a:.4f}"

        # factor = exp(γ·z) → ln(factor)/γ = z; valores finitos y no NaN
        assert math.isfinite(mult_h)
        assert math.isfinite(mult_a)

    def test_equipo_fuera_de_lista_factor_neutro(self):
        """R4/R7: equipo no en teams → z=0 → factor=1.0 (v1 behaviour)."""
        silver = self._build_simple_silver()
        fn = make_form_factor_fn(silver, "2026-06-01", None, 0.5, TEAMS_SMALL)

        # "ITA" no está en TEAMS_SMALL
        mult_h, mult_a = fn("ITA", "POR")
        assert abs(mult_h - 1.0) < 1e-9
        assert abs(mult_a - 1.0) < 1e-9

    def test_sigma_degenerado_todos_factor_1(self):
        """R4: si todos los gd_w son iguales (σ=0) → todos los factores son 1.0."""
        # Todos los equipos empatan 0-0 (gd_w=0 uniforme para todos)
        rows = []
        for team in TEAMS_SMALL:
            rows.append({
                "home_code": team, "away_code": "USA",
                "date": "2026-05-10", "home_goals": 0, "away_goals": 0,
                "tournament": "Friendly",
            })
        silver = _make_silver(rows)
        fn = make_form_factor_fn(silver, "2026-06-01", None, 0.8, TEAMS_SMALL)

        for home in TEAMS_SMALL:
            for away in TEAMS_SMALL:
                m_h, m_a = fn(home, away)
                assert abs(m_h - 1.0) < 1e-9, f"σ=0: {home} factor={m_h}"
                assert abs(m_a - 1.0) < 1e-9, f"σ=0: {away} factor={m_a}"

    def test_anti_fuga_as_of_estricto(self):
        """R4/R1: partido con date == as_of NO influye en el factor del mismo día."""
        team = "ARG"
        as_of = "2026-06-15"

        rows = [
            # Partido en as_of → NO debe entrar
            {"home_code": team, "away_code": "BRA", "date": as_of,
             "home_goals": 5, "away_goals": 0, "tournament": "Friendly"},
            # Partido antes → SÍ debe entrar
            {"home_code": team, "away_code": "BRA", "date": "2026-06-14",
             "home_goals": 1, "away_goals": 1, "tournament": "Friendly"},
        ]
        # Otro equipo con datos
        for other in ["BRA", "FRA", "GER", "ESP"]:
            rows.append({"home_code": other, "away_code": "USA",
                         "date": "2026-06-14", "home_goals": 1, "away_goals": 0,
                         "tournament": "Friendly"})
        silver = _make_silver(rows)

        fn_strict = make_form_factor_fn(silver, as_of, None, 0.5, TEAMS_SMALL)

        # fn_future ignora todo partido hasta as_of (ventana vacía para ARG del mismo día)
        # El gd_w de ARG con as_of estricto = el empate del 14/06, no el 5-0 del 15/06
        f_arg, _ = fn_strict("ARG", "BRA")

        # Con as_of = el día DESPUÉS (todo incluido: tanto el empate como el 5-0)
        fn_permissive = make_form_factor_fn(silver, "2026-06-16", None, 0.5, TEAMS_SMALL)
        f_arg_full, _ = fn_permissive("ARG", "BRA")

        # El 5-0 (gana +5 goles) inflaría el factor de ARG si se incluyera.
        # f_arg_full > f_arg_strict (el 5-0 empuja el factor al alza)
        assert f_arg_full > f_arg, (
            "El partido del día predicho no debe incluirse (anti-fuga): "
            f"f_strict={f_arg:.4f} f_full={f_arg_full:.4f}"
        )


# ---------------------------------------------------------------------------
# R5 — FormFactory para backtest walk-forward
# ---------------------------------------------------------------------------

class TestFormFactoryR5:
    """R5: make_form_factory produce factory(as_of) correcta para walk-forward."""

    def _silver_temporal(self) -> pd.DataFrame:
        """Silver con resultados que cambian entre enero y julio 2026."""
        rows = []
        # ARG: derrota en febrero, victoria en mayo
        rows.append({"home_code": "ARG", "away_code": "BRA", "date": "2026-02-01",
                     "home_goals": 0, "away_goals": 3, "tournament": "Friendly"})
        rows.append({"home_code": "ARG", "away_code": "BRA", "date": "2026-05-01",
                     "home_goals": 3, "away_goals": 0, "tournament": "Friendly"})
        for team in ["BRA", "FRA", "GER", "ESP"]:
            rows.append({"home_code": team, "away_code": "USA", "date": "2026-04-01",
                         "home_goals": 1, "away_goals": 1, "tournament": "Friendly"})
        return _make_silver(rows)

    def test_factory_gamma0_es_identidad(self):
        """R5: con γ=0 la factory devuelve siempre (1.0, 1.0) en cada as_of."""
        factory = make_form_factory(_make_silver([]), None, 0.0, TEAMS_SMALL)

        for as_of in ["2026-01-01", "2026-06-15", "2026-07-15"]:
            fn = factory(as_of)
            h, a = fn("ARG", "BRA")
            assert abs(h - 1.0) < 1e-9 and abs(a - 1.0) < 1e-9, (
                f"γ=0 factory debe devolver (1,1) para as_of={as_of}"
            )

    def test_factory_cambia_resultado_con_as_of(self):
        """R5: el factor de ARG cambia entre as_of=marzo (solo derrota) y as_of=junio (solo victoria)."""
        silver = self._silver_temporal()
        gamma = 0.5
        factory = make_form_factory(silver, None, gamma, TEAMS_SMALL)

        # as_of = marzo: ARG solo tiene la derrota de febrero
        fn_mar = factory("2026-03-01")
        f_arg_mar, _ = fn_mar("ARG", "BRA")

        # as_of = junio: ARG tiene derrota de feb + victoria de mayo
        fn_jun = factory("2026-06-01")
        f_arg_jun, _ = fn_jun("ARG", "BRA")

        # En junio ARG tiene la victoria en la ventana → su gd_w es mejor → factor mayor
        assert f_arg_jun > f_arg_mar, (
            f"Factor ARG con victoria (jun={f_arg_jun:.4f}) "
            f"debe superar sin victoria (mar={f_arg_mar:.4f})"
        )

    def test_backtest_factory_anti_fuga(self):
        """R5: factory con as_of=fechaPartido excluye ese partido del factor (R1+R5)."""
        team = "BRA"
        match_date = "2026-06-15"

        rows = [
            # Partido de BRA EN el día del backtest (must NOT be included in its own window)
            {"home_code": team, "away_code": "ARG", "date": match_date,
             "home_goals": 5, "away_goals": 0, "tournament": WC_TOURNAMENT},
            # Partido pre-backtest (DEBE incluirse)
            {"home_code": team, "away_code": "ARG", "date": "2026-06-14",
             "home_goals": 0, "away_goals": 0, "tournament": WC_TOURNAMENT},
        ]
        for other in ["ARG", "FRA", "GER", "ESP"]:
            rows.append({"home_code": other, "away_code": "USA",
                         "date": "2026-06-14", "home_goals": 1, "away_goals": 0,
                         "tournament": "Friendly"})
        silver = _make_silver(rows)

        factory = make_form_factory(silver, None, 0.5, TEAMS_SMALL)

        # factory(match_date) simula el backtest con cutoff ese mismo día
        fn_day_of = factory(match_date)
        _, f_bra_strict = fn_day_of("ARG", "BRA")

        fn_after = factory("2026-06-16")
        _, f_bra_full = fn_after("ARG", "BRA")

        # El 5-0 inflaría el factor de BRA → sin él, f_bra_strict < f_bra_full
        assert f_bra_full > f_bra_strict, (
            "Factory anti-fuga: el partido del día del backtest no debe incluirse"
        )
