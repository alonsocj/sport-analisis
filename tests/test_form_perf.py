"""tests/test_form_perf.py — Feature 18: forma_perf. R1, R2, R3, R4.

Trazabilidad (tasks.md):
| R1 | test_indice_una_sola_pasada, test_build_window_from_bucket_equivale |
| R2 | test_factores_identicos_ruta_clasica_1e9, test_z_por_equipo_identicas |
| R3 | test_build_window_api_estable |
| R4 | test_escala_no_recorre_df_por_equipo |

100% offline — sin red, sin reloj (as_of inyectado), sin dependencias nuevas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.form.config import DEFAULT_FORM_CONFIG, WC2026_START_DATE, WC_TOURNAMENT
from src.form.factor import make_form_factor_fn
from src.form.metrics import team_form
from src.form.window import (
    MatchInWindow,
    build_window,
    build_window_from_bucket,
    index_matches_by_team,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEAMS = ["ARG", "BRA", "FRA", "GER", "ESP", "MEX", "USA", "POR"]


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


def _make_rich_silver(teams: list[str]) -> pd.DataFrame:
    """Silver sintético con diversidad: pre-WC, grupo WC, como local y visitante."""
    rows: list[dict] = []
    for i, team in enumerate(teams):
        # Partidos pre-WC como local
        for j in range(4):
            rows.append({
                "home_code": team,
                "away_code": teams[(i + j + 1) % len(teams)],
                "date": f"2026-0{(j % 5) + 1:01d}-{(j * 3 + 1):02d}",
                "home_goals": (i + j) % 4,
                "away_goals": j % 3,
                "tournament": "Friendly",
            })
        # Partido WC grupo como visitante
        rows.append({
            "home_code": teams[(i + 1) % len(teams)],
            "away_code": team,
            "date": f"2026-06-{12 + (i % 5):02d}",
            "home_goals": 1,
            "away_goals": (i % 2),
            "tournament": WC_TOURNAMENT,
        })
    return _make_silver(rows)


def _classic_build_window(
    matches: pd.DataFrame,
    team: str,
    as_of: str,
    k_pre: int = 5,
) -> list[MatchInWindow]:
    """Oráculo: implementación original de build_window (Feature 16 iterrows).

    Codificada inline para independencia del módulo; garantiza que el test
    no puede auto-satisfacerse con la nueva implementación.
    """
    wc_group: list[MatchInWindow] = []
    pre_wc: list[MatchInWindow] = []

    for _, row in matches.iterrows():
        home = str(row.get("home_code", ""))
        away = str(row.get("away_code", ""))
        if home != team and away != team:
            continue
        match_date = str(row.get("date", ""))
        if not match_date or match_date >= as_of:
            continue
        try:
            home_g = int(float(row["home_goals"]))
            away_g = int(float(row["away_goals"]))
        except (ValueError, TypeError, KeyError):
            continue
        tournament = str(row.get("tournament", ""))
        is_wc2026_group = (tournament == WC_TOURNAMENT) and (match_date >= WC2026_START_DATE)
        if team == home:
            gf, ga, opp = home_g, away_g, away
        else:
            gf, ga, opp = away_g, home_g, home
        if gf > ga:
            result = "W"
        elif gf < ga:
            result = "L"
        else:
            result = "D"
        record = MatchInWindow(
            date=match_date,
            is_group_wc=is_wc2026_group,
            gf=gf,
            ga=ga,
            opp_code=opp,
            result=result,
        )
        if is_wc2026_group:
            wc_group.append(record)
        else:
            pre_wc.append(record)

    wc_group.sort(key=lambda m: m.date)
    pre_wc.sort(key=lambda m: m.date)
    wc_selected = wc_group[-3:] if len(wc_group) > 3 else wc_group
    pre_selected = pre_wc[-k_pre:] if len(pre_wc) > k_pre else pre_wc
    return sorted(wc_selected + pre_selected, key=lambda m: m.date)


# ---------------------------------------------------------------------------
# R1 — Indexación en una sola pasada
# ---------------------------------------------------------------------------

class TestR1IndexacionUnaSolaPasada:
    """R1: index_matches_by_team recorre el DataFrame UNA sola vez."""

    def test_indice_una_sola_pasada(self):
        """R1 (gate): index_matches_by_team llama itertuples exactamente 1 vez."""
        matches = _make_rich_silver(TEAMS)
        teams = TEAMS[:]

        call_count: list[int] = [0]
        _real_itertuples = matches.itertuples

        def _counting_itertuples(*args, **kwargs):
            call_count[0] += 1
            return _real_itertuples(*args, **kwargs)

        matches.itertuples = _counting_itertuples  # type: ignore[method-assign]

        index_matches_by_team(matches, teams)

        assert call_count[0] == 1, (
            f"index_matches_by_team debe llamar itertuples 1 vez, llamó {call_count[0]}"
        )

    def test_build_window_from_bucket_equivale(self):
        """R1: build_window_from_bucket produce el mismo resultado que el oráculo clásico."""
        matches = _make_rich_silver(TEAMS)
        as_of = "2026-06-20"
        k_pre = 5

        index = index_matches_by_team(matches, TEAMS)

        for team in TEAMS:
            bucket = index.get(team, [])
            resultado_nuevo = build_window_from_bucket(bucket, as_of, k_pre)
            resultado_clasico = _classic_build_window(matches, team, as_of, k_pre)

            assert resultado_nuevo == resultado_clasico, (
                f"build_window_from_bucket difiere del oráculo para {team}: "
                f"nuevo={resultado_nuevo}, clasico={resultado_clasico}"
            )

    def test_bucket_vacio_ventana_vacia(self):
        """R1: bucket vacío → ventana vacía sin error."""
        assert build_window_from_bucket([], "2026-06-20") == []

    def test_indice_equipos_no_presentes(self):
        """R1: equipo sin partidos → bucket vacío en el índice."""
        matches = _make_silver([{
            "home_code": "ARG", "away_code": "BRA",
            "date": "2026-06-12", "home_goals": 1, "away_goals": 0,
            "tournament": WC_TOURNAMENT,
        }])
        index = index_matches_by_team(matches, ["ARG", "BRA", "FRA"])
        assert index["FRA"] == []
        assert len(index["ARG"]) == 1
        assert len(index["BRA"]) == 1


# ---------------------------------------------------------------------------
# R2 — Equivalencia exacta con Feature 16
# ---------------------------------------------------------------------------

class TestR2EquivalenciaExacta:
    """R2: factores y z por equipo idénticos a la ruta clásica (tol 1e-9)."""

    def _make_factor_clasico(
        self,
        matches: pd.DataFrame,
        as_of: str,
        gamma: float,
        teams: list[str],
    ) -> dict[str, float]:
        """Calcula z por equipo usando el oráculo clásico build_window por equipo."""
        elo_dict: dict[str, float] = {}
        cfg = DEFAULT_FORM_CONFIG

        gd_w_by_team: dict[str, float] = {}
        for team in teams:
            window = _classic_build_window(matches, team, as_of, cfg.k_pre)
            metrics = team_form(
                window, elo_dict,
                decay=cfg.decay, tier_ratio=cfg.tier_ratio,
                opp_elo_pivot=cfg.opp_elo_pivot, opp_scale=cfg.opp_scale,
            )
            gd_w_by_team[team] = metrics.gd_w

        values = np.array([gd_w_by_team[t] for t in teams], dtype=float)
        mu = float(np.mean(values))
        sigma = float(np.std(values))

        z_by_team: dict[str, float] = {}
        for team in teams:
            if sigma < 1e-10:
                z_by_team[team] = 0.0
            else:
                z_by_team[team] = (gd_w_by_team[team] - mu) / sigma
        return z_by_team

    def test_factores_identicos_ruta_clasica_1e9(self):
        """R2 (gate): factores (mult_home, mult_away) idénticos a ruta clásica, tol 1e-9."""
        matches = _make_rich_silver(TEAMS)
        as_of = "2026-06-20"
        gamma = 0.3

        fn_nuevo = make_form_factor_fn(matches, as_of, None, gamma, TEAMS)
        z_clasico = self._make_factor_clasico(matches, as_of, gamma, TEAMS)

        for home in TEAMS:
            for away in TEAMS:
                mult_h, mult_a = fn_nuevo(home, away)
                import math
                z_h_clasico = z_clasico[home]
                z_a_clasico = z_clasico[away]
                esperado_h = float(math.exp(gamma * z_h_clasico))
                esperado_a = float(math.exp(gamma * z_a_clasico))
                assert abs(mult_h - esperado_h) < 1e-9, (
                    f"mult_home diverge para {home}: nuevo={mult_h}, clasico={esperado_h}"
                )
                assert abs(mult_a - esperado_a) < 1e-9, (
                    f"mult_away diverge para {away}: nuevo={mult_a}, clasico={esperado_a}"
                )

    def test_z_por_equipo_identicas(self):
        """R2: z por equipo idénticos entre ruta nueva y ruta clásica (tol 1e-9)."""
        matches = _make_rich_silver(TEAMS)
        as_of = "2026-06-18"
        gamma = 0.5

        fn_nuevo = make_form_factor_fn(matches, as_of, None, gamma, TEAMS)
        z_clasico = self._make_factor_clasico(matches, as_of, gamma, TEAMS)

        import math
        for team in TEAMS:
            mult_h, _ = fn_nuevo(team, TEAMS[0])
            z_nuevo = math.log(mult_h) / gamma if abs(mult_h) > 1e-15 else 0.0
            assert abs(z_nuevo - z_clasico[team]) < 1e-9, (
                f"z diverge para {team}: nuevo={z_nuevo:.9f}, clasico={z_clasico[team]:.9f}"
            )

    def test_gamma0_identidad_exacta_v1(self):
        """R2/R5: γ=0 → factor (1.0, 1.0) exacto para todos los equipos (v1 exacto)."""
        matches = _make_rich_silver(TEAMS)
        fn = make_form_factor_fn(matches, "2026-06-20", None, 0.0, TEAMS)
        for home in TEAMS:
            for away in TEAMS:
                h, a = fn(home, away)
                assert abs(h - 1.0) < 1e-9 and abs(a - 1.0) < 1e-9, (
                    f"γ=0 debe dar (1,1), obtenido ({h}, {a}) para {home} vs {away}"
                )

    def test_equivalencia_con_partidos_misma_fecha(self):
        """R2: partidos con misma fecha mantienen el orden estable (equivalencia oráculo)."""
        team = "ARG"
        as_of = "2026-06-20"
        # Varios partidos con la misma fecha (desempate por orden de aparición)
        rows = [
            {"home_code": "ARG", "away_code": "BRA", "date": "2026-05-01",
             "home_goals": 2, "away_goals": 1, "tournament": "Friendly"},
            {"home_code": "ARG", "away_code": "FRA", "date": "2026-05-01",
             "home_goals": 0, "away_goals": 0, "tournament": "Friendly"},
            {"home_code": "ARG", "away_code": "GER", "date": "2026-05-01",
             "home_goals": 3, "away_goals": 2, "tournament": "Friendly"},
            {"home_code": "ARG", "away_code": "ESP", "date": "2026-05-01",
             "home_goals": 1, "away_goals": 1, "tournament": "Friendly"},
            {"home_code": "ARG", "away_code": "MEX", "date": "2026-05-01",
             "home_goals": 2, "away_goals": 0, "tournament": "Friendly"},
            {"home_code": "ARG", "away_code": "USA", "date": "2026-05-01",
             "home_goals": 4, "away_goals": 1, "tournament": "Friendly"},
        ]
        matches = _make_silver(rows)

        index = index_matches_by_team(matches, [team])
        resultado_nuevo = build_window_from_bucket(index[team], as_of, k_pre=5)
        resultado_clasico = _classic_build_window(matches, team, as_of, k_pre=5)

        assert resultado_nuevo == resultado_clasico, (
            f"Desempate por fecha igual difiere: nuevo={resultado_nuevo}, "
            f"clasico={resultado_clasico}"
        )


# ---------------------------------------------------------------------------
# R3 — API pública estable
# ---------------------------------------------------------------------------

class TestR3ApiEstable:
    """R3: build_window mantiene firma y semántica públicas intactas."""

    def test_build_window_api_estable(self):
        """R3: build_window(matches, team, as_of, k_pre) devuelve resultado correcto."""
        matches = _make_rich_silver(TEAMS)
        as_of = "2026-06-20"

        for team in TEAMS:
            resultado = build_window(matches, team, as_of, k_pre=5)
            clasico = _classic_build_window(matches, team, as_of, k_pre=5)
            assert resultado == clasico, (
                f"build_window difiere del oráculo para {team}"
            )

    def test_build_window_anti_fuga_preservada(self):
        """R3: date == as_of sigue siendo excluido (anti-fuga, R1 de F16)."""
        team = "BRA"
        as_of = "2026-06-15"
        matches = _make_silver([
            {"home_code": team, "away_code": "ARG", "date": as_of,
             "home_goals": 5, "away_goals": 0, "tournament": WC_TOURNAMENT},
            {"home_code": team, "away_code": "ARG", "date": "2026-06-14",
             "home_goals": 1, "away_goals": 0, "tournament": WC_TOURNAMENT},
        ])
        window = build_window(matches, team, as_of)
        assert len(window) == 1
        assert window[0].date == "2026-06-14"


# ---------------------------------------------------------------------------
# R4 — Escala: no crece multiplicativamente con N
# ---------------------------------------------------------------------------

class TestR4EscalaNoMultiplicativa:
    """R4: coste de indexación no crece con N equipos (una sola pasada)."""

    def test_escala_no_recorre_df_por_equipo(self):
        """R4: index_matches_by_team llama itertuples 1 vez para 1 equipo Y para 48 equipos."""
        # Fixture grande (~1000 filas)
        teams_large = [f"T{i:02d}" for i in range(48)]
        rows: list[dict] = []
        for i in range(len(teams_large)):
            for j in range(20):
                rows.append({
                    "home_code": teams_large[i],
                    "away_code": teams_large[(i + j + 1) % len(teams_large)],
                    "date": f"2025-{(j % 11) + 1:02d}-{(j % 28) + 1:02d}",
                    "home_goals": j % 5,
                    "away_goals": (j + 1) % 4,
                    "tournament": "Friendly",
                })
        matches = _make_silver(rows)

        # Verificar que el número de llamadas a itertuples es SIEMPRE 1,
        # sin importar si pasamos 1 equipo o 48 equipos.
        for n_teams in [1, 8, 48]:
            subset = teams_large[:n_teams]
            call_count: list[int] = [0]
            _real = matches.itertuples

            def _counting(*args, _real=_real, _cc=call_count, **kwargs):
                _cc[0] += 1
                return _real(*args, **kwargs)

            matches.itertuples = _counting  # type: ignore[method-assign]

            index_matches_by_team(matches, subset)

            # Restore
            matches.itertuples = _real  # type: ignore[method-assign]

            assert call_count[0] == 1, (
                f"Para {n_teams} equipos, se esperaba 1 llamada a itertuples, "
                f"se hicieron {call_count[0]}"
            )
