"""tests/test_forma_reciente.py — Feature 16: forma_reciente, R1 y R2.

Trazabilidad (tasks.md):
| R1 | test_ventana_3grupo_5prewc, test_filtro_estricto_as_of_anti_fuga,
|    | test_equipo_sin_partidos_ventana_parcial                              |
| R2 | test_pesos_recencia_decay, test_tier_grupo_pesa_mas_que_amistoso,
|    | test_metricas_oraculo_deterministas                                   |

100% offline — fixtures sintéticos en memoria, sin red, sin reloj (as_of inyectado).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.form.config import DEFAULT_FORM_CONFIG, WC2026_START_DATE, WC_TOURNAMENT
from src.form.metrics import FormMetrics, team_form
from src.form.window import MatchInWindow, build_window


# ---------------------------------------------------------------------------
# Helpers para construir DataFrames sintéticos
# ---------------------------------------------------------------------------

def _make_matches(rows: list[dict]) -> pd.DataFrame:
    """Construye un DataFrame de silver mínimo a partir de una lista de dicts."""
    defaults = {
        "match_id": "TEST",
        "date": "2026-01-01",
        "home_code": "AAA",
        "away_code": "BBB",
        "home_goals": 1,
        "away_goals": 0,
        "tournament": "Friendly",
        "neutral": False,
    }
    full_rows = [{**defaults, **r} for r in rows]
    return pd.DataFrame(full_rows)


# ---------------------------------------------------------------------------
# R1 — Ventana corta por equipo, leak-free
# ---------------------------------------------------------------------------

class TestVentanaR1:
    """R1: build_window construye la ventana correcta con filtro estricto anti-fuga."""

    def test_ventana_3grupo_5prewc(self):
        """R1: toma máximo 3 partidos de grupo WC2026 + máximo 5 pre-WC."""
        team = "ARG"
        rows = []

        # 4 partidos de grupo WC2026 (solo 3 deberían entrar)
        for day in range(1, 5):
            rows.append({
                "home_code": team,
                "away_code": "BRA",
                "date": f"2026-06-{11 + day:02d}",
                "home_goals": 1,
                "away_goals": 0,
                "tournament": WC_TOURNAMENT,
            })

        # 6 partidos pre-WC (solo 5 deberían entrar: los más recientes)
        for month in range(1, 7):
            rows.append({
                "home_code": team,
                "away_code": "CHI",
                "date": f"2026-0{month}-01",
                "home_goals": 2,
                "away_goals": 1,
                "tournament": "Friendly",
            })

        matches = _make_matches(rows)
        # as_of posterior a todos los partidos
        window = build_window(matches, team, as_of="2026-07-01", k_pre=5)

        wc_group = [m for m in window if m.is_group_wc]
        pre_wc = [m for m in window if not m.is_group_wc]

        assert len(wc_group) == 3, f"Se esperaban 3 partidos de grupo WC, hay {len(wc_group)}"
        assert len(pre_wc) == 5, f"Se esperaban 5 partidos pre-WC, hay {len(pre_wc)}"
        assert len(window) == 8

    def test_filtro_estricto_as_of_anti_fuga(self):
        """R1: partido con date == as_of NO debe entrar en la ventana (filtro estricto)."""
        team = "MEX"
        as_of = "2026-06-15"

        rows = [
            # Partido exactamente en as_of → excluido
            {
                "home_code": team,
                "away_code": "USA",
                "date": as_of,
                "home_goals": 1,
                "away_goals": 1,
                "tournament": WC_TOURNAMENT,
            },
            # Partido antes de as_of → incluido
            {
                "home_code": team,
                "away_code": "CAN",
                "date": "2026-06-12",
                "home_goals": 2,
                "away_goals": 0,
                "tournament": WC_TOURNAMENT,
            },
        ]
        matches = _make_matches(rows)
        window = build_window(matches, team, as_of=as_of)

        dates = [m.date for m in window]
        assert as_of not in dates, "El partido predicho no debe estar en su propia ventana (anti-fuga)"
        assert "2026-06-12" in dates, "El partido previo debe estar en la ventana"
        assert len(window) == 1

    def test_equipo_sin_partidos_ventana_parcial(self):
        """R1: equipo con 0 partidos → ventana vacía sin error (degradación graceful)."""
        matches = _make_matches([
            {
                "home_code": "BRA",
                "away_code": "FRA",
                "date": "2026-06-12",
                "home_goals": 1,
                "away_goals": 0,
                "tournament": WC_TOURNAMENT,
            }
        ])
        # ARG no aparece en los datos
        window = build_window(matches, "ARG", as_of="2026-07-01")
        assert window == [], "Ventana vacía esperada para equipo sin partidos"

    def test_ventana_solo_wc_sin_prewc(self):
        """R1: equipo con solo partidos WC grupo → ventana parcial, sin error."""
        team = "FRA"
        rows = [
            {
                "home_code": team,
                "away_code": "GER",
                "date": f"2026-06-{12 + i:02d}",
                "home_goals": 1,
                "away_goals": 0,
                "tournament": WC_TOURNAMENT,
            }
            for i in range(2)
        ]
        matches = _make_matches(rows)
        window = build_window(matches, team, as_of="2026-07-01")
        assert len(window) == 2
        assert all(m.is_group_wc for m in window)

    def test_ventana_ordena_ascendente(self):
        """R1: ventana devuelta en orden ascendente por fecha (más antiguo primero)."""
        team = "GER"
        rows = [
            {"home_code": team, "away_code": "ESP", "date": "2026-05-01", "home_goals": 1, "away_goals": 0, "tournament": "Friendly"},
            {"home_code": team, "away_code": "FRA", "date": "2026-04-01", "home_goals": 0, "away_goals": 0, "tournament": "Friendly"},
            {"home_code": team, "away_code": "ITA", "date": "2026-03-01", "home_goals": 2, "away_goals": 1, "tournament": "Friendly"},
        ]
        matches = _make_matches(rows)
        window = build_window(matches, team, as_of="2026-06-01")
        dates = [m.date for m in window]
        assert dates == sorted(dates), "La ventana debe estar ordenada ascendente"

    def test_partidos_sin_marcador_excluidos(self):
        """R1: partidos sin goles numéricos son descartados silenciosamente."""
        team = "ESP"
        rows = [
            {"home_code": team, "away_code": "POR", "date": "2026-06-12", "home_goals": "NA", "away_goals": "NA", "tournament": WC_TOURNAMENT},
            {"home_code": team, "away_code": "FRA", "date": "2026-06-11", "home_goals": 2, "away_goals": 1, "tournament": WC_TOURNAMENT},
        ]
        matches = _make_matches(rows)
        window = build_window(matches, team, as_of="2026-07-01")
        assert len(window) == 1
        assert window[0].date == "2026-06-11"

    def test_equipo_como_visitante_incluido(self):
        """R1: incluye partidos donde el equipo es visitante."""
        team = "BRA"
        rows = [
            {"home_code": "ARG", "away_code": team, "date": "2026-06-12", "home_goals": 0, "away_goals": 3, "tournament": WC_TOURNAMENT},
        ]
        matches = _make_matches(rows)
        window = build_window(matches, team, as_of="2026-07-01")
        assert len(window) == 1
        assert window[0].gf == 3   # BRA marcó 3 (era visitante)
        assert window[0].ga == 0
        assert window[0].result == "W"
        assert window[0].opp_code == "ARG"


# ---------------------------------------------------------------------------
# R2 — Métricas de forma deterministas, ponderadas por recencia
# ---------------------------------------------------------------------------

class TestMetricasR2:
    """R2: team_form calcula métricas correctas, deterministas, ponderadas por recencia."""

    def test_pesos_recencia_decay(self):
        """R2: el partido más reciente tiene el mayor peso (decay^0 > decay^1 > ...)."""
        # Con tier=1 y q=1, el peso depende solo del rank: w = decay^rank
        # rank=0 = más reciente, rank=n-1 = más antiguo
        # Dos partidos: más reciente (i=1 en ventana ascendente) → rank=0 → w=1.0
        #               más antiguo  (i=0 en ventana ascendente) → rank=1 → w=decay
        decay = DEFAULT_FORM_CONFIG.decay
        window = [
            MatchInWindow(date="2026-05-01", is_group_wc=False, gf=0, ga=3, opp_code="XXX", result="L"),
            MatchInWindow(date="2026-06-01", is_group_wc=False, gf=3, ga=0, opp_code="YYY", result="W"),
        ]
        elo: dict[str, float] = {}  # q=1.0 neutro
        metrics = team_form(window, elo, decay=decay, tier_ratio=1.0)

        # gd_w = (decay^1 * (-3) + decay^0 * 3) / (decay + 1)
        # Con decay=0.85: (-3*0.85 + 3*1.0) / (0.85 + 1.0) = (-2.55 + 3.0) / 1.85 = 0.45/1.85
        expected_gd_w = (decay * (-3) + 1.0 * 3) / (decay + 1.0)
        assert abs(metrics.gd_w - expected_gd_w) < 1e-9, (
            f"gd_w esperado {expected_gd_w:.6f}, obtenido {metrics.gd_w:.6f}"
        )
        # Positivo → el partido más reciente (victoria por 3-0) domina
        assert metrics.gd_w > 0

    def test_tier_grupo_pesa_mas_que_amistoso(self):
        """R2: partido de grupo WC pesa tier_ratio=2× más que amistoso pre-WC."""
        tier_ratio = DEFAULT_FORM_CONFIG.tier_ratio  # 2.0
        decay = DEFAULT_FORM_CONFIG.decay

        # Mismo resultado, dos partidos: amistoso (rank 1) y WC grupo (rank 0)
        # El grupo pesa tier_ratio más
        window = [
            MatchInWindow(date="2026-05-01", is_group_wc=False, gf=0, ga=2, opp_code="XXX", result="L"),  # rank 1
            MatchInWindow(date="2026-06-12", is_group_wc=True, gf=2, ga=0, opp_code="YYY", result="W"),   # rank 0
        ]
        elo: dict[str, float] = {}
        metrics = team_form(window, elo, decay=decay, tier_ratio=tier_ratio)

        # w_amistoso = decay^1 * 1.0 = 0.85
        # w_grupo    = decay^0 * tier_ratio = 1.0 * 2.0 = 2.0
        # gd_w = (0.85 * (-2) + 2.0 * 2) / (0.85 + 2.0) = (-1.7 + 4.0) / 2.85
        w_pre = decay ** 1 * 1.0
        w_wc = decay ** 0 * tier_ratio
        expected_gd_w = (w_pre * (-2) + w_wc * 2) / (w_pre + w_wc)
        assert abs(metrics.gd_w - expected_gd_w) < 1e-9

        # El partido de grupo WC domina → gd_w debe ser positivo
        assert metrics.gd_w > 0

    def test_metricas_oraculo_deterministas(self):
        """R2: dado el mismo input, team_form devuelve exactamente el mismo output (determinismo)."""
        window = [
            MatchInWindow(date="2026-06-11", is_group_wc=True, gf=2, ga=1, opp_code="URU", result="W"),
            MatchInWindow(date="2026-06-15", is_group_wc=True, gf=1, ga=1, opp_code="JPN", result="D"),
        ]
        elo = {"URU": 1750.0, "JPN": 1650.0}

        result1 = team_form(window, elo)
        result2 = team_form(window, elo)

        assert result1.gf_w == result2.gf_w
        assert result1.gd_w == result2.gd_w
        assert result1.ppg_w == result2.ppg_w
        assert result1.streak == result2.streak

    def test_ventana_vacia_devuelve_ceros(self):
        """R2/R7: ventana vacía devuelve FormMetrics con todos ceros y streak vacío."""
        metrics = team_form([], {})
        assert metrics.gf_w == 0.0
        assert metrics.ga_w == 0.0
        assert metrics.gd_w == 0.0
        assert metrics.ppg_w == 0.0
        assert metrics.streak == ""

    def test_racha_mas_reciente_primero(self):
        """R2: streak tiene los resultados más recientes primero."""
        window = [
            MatchInWindow(date="2026-04-01", is_group_wc=False, gf=1, ga=0, opp_code="A", result="W"),  # oldest
            MatchInWindow(date="2026-05-01", is_group_wc=False, gf=0, ga=1, opp_code="B", result="L"),
            MatchInWindow(date="2026-06-01", is_group_wc=False, gf=1, ga=1, opp_code="C", result="D"),  # most recent
        ]
        metrics = team_form(window, {})
        # streak debe ser "DLW" (más reciente primero)
        assert metrics.streak == "DLW"

    def test_goles_promedio_ponderados(self):
        """R2: gf_w, ga_w son promedios ponderados correctos."""
        # Un partido único: gf=3, ga=1, tier=1 (amistoso), q=1, rank=0 → w=1.0
        window = [
            MatchInWindow(date="2026-05-01", is_group_wc=False, gf=3, ga=1, opp_code="X", result="W"),
        ]
        metrics = team_form(window, {})
        assert abs(metrics.gf_w - 3.0) < 1e-9
        assert abs(metrics.ga_w - 1.0) < 1e-9
        assert abs(metrics.gd_w - 2.0) < 1e-9

    def test_ppg_victoria_derrota_empate(self):
        """R2: ppg_w es 3.0 para victoria pura, 0.0 para derrota pura, 1.0 para empate."""
        elo: dict[str, float] = {}

        # Victoria
        w_win = [MatchInWindow(date="2026-06-01", is_group_wc=False, gf=2, ga=0, opp_code="X", result="W")]
        assert abs(team_form(w_win, elo).ppg_w - 3.0) < 1e-9

        # Derrota
        w_loss = [MatchInWindow(date="2026-06-01", is_group_wc=False, gf=0, ga=1, opp_code="X", result="L")]
        assert abs(team_form(w_loss, elo).ppg_w - 0.0) < 1e-9

        # Empate
        w_draw = [MatchInWindow(date="2026-06-01", is_group_wc=False, gf=1, ga=1, opp_code="X", result="D")]
        assert abs(team_form(w_draw, elo).ppg_w - 1.0) < 1e-9
