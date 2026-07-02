"""Tests del motor generico de conteo O/U (Feature 25: R1, R2, R4, R5).

Todos offline: sin red, sin modelo entrenado, sin archivos de produccion.
Los fixtures de silver son DataFrames construidos en memoria.

Trazabilidad (tasks.md):
  R1 <- test_shrinkage_por_stat
         test_anti_fuga_as_of
         test_stat_ausente_degrada
  R2 <- test_over_under_poisson_suma_uno_por_stat
         test_lineas_default_por_stat
  R4 <- test_app_mercados_incluye_stats_o_degrada
         test_tarjetas_lleva_aviso_ruido
  R5 <- (transversal: todos los tests son offline, as_of inyectado, sin libs nuevas)
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.markets.counts import (
    STAT_SPECS,
    CountConfig,
    CountOULine,
    CountSummary,
    count_over_under,
    count_rates,
    count_summary,
    expected_counts,
)


# ---------------------------------------------------------------------------
# Fixture base comun: 6 partidos con cards, shots y shots_on_target
# ARG: 3 partidos  (home 2x, away 1x)
# BRA: 2 partidos  (home 1x, away 1x)
# ---------------------------------------------------------------------------

_AS_OF = "2026-06-10"  # todos los partidos anteriores quedan incluidos

MATCHES_BASE = pd.DataFrame(
    [
        {
            "date": "2026-06-01",
            "home_code": "ARG",
            "away_code": "BRA",
            "home_cards": 3.0,
            "away_cards": 2.0,
            "home_shots": 18.0,
            "away_shots": 12.0,
            "home_shots_on_target": 7.0,
            "away_shots_on_target": 4.0,
        },
        {
            "date": "2026-06-02",
            "home_code": "MEX",
            "away_code": "ARG",
            "home_cards": 1.0,
            "away_cards": 4.0,
            "home_shots": 10.0,
            "away_shots": 20.0,
            "home_shots_on_target": 3.0,
            "away_shots_on_target": 8.0,
        },
        {
            "date": "2026-06-03",
            "home_code": "ARG",
            "away_code": "USA",
            "home_cards": 2.0,
            "away_cards": 3.0,
            "home_shots": 22.0,
            "away_shots": 9.0,
            "home_shots_on_target": 9.0,
            "away_shots_on_target": 3.0,
        },
        {
            "date": "2026-06-04",
            "home_code": "BRA",
            "away_code": "MEX",
            "home_cards": 2.0,
            "away_cards": 1.0,
            "home_shots": 15.0,
            "away_shots": 11.0,
            "home_shots_on_target": 6.0,
            "away_shots_on_target": 4.0,
        },
        {
            "date": "2026-06-05",
            "home_code": "USA",
            "away_code": "CAN",
            "home_cards": 1.0,
            "away_cards": 2.0,
            "home_shots": 14.0,
            "away_shots": 13.0,
            "home_shots_on_target": 5.0,
            "away_shots_on_target": 5.0,
        },
        {
            "date": "2026-06-06",
            "home_code": "MEX",
            "away_code": "CAN",
            "home_cards": 3.0,
            "away_cards": 2.0,
            "home_shots": 16.0,
            "away_shots": 10.0,
            "home_shots_on_target": 6.0,
            "away_shots_on_target": 3.0,
        },
    ]
)


# ---------------------------------------------------------------------------
# R1 — test_shrinkage_por_stat
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stat", ["cards", "shots", "sot"])
def test_shrinkage_por_stat(stat: str) -> None:
    """Con n=1 y k=5, la tasa de att debe estar entre raw_mean y mu_global (R1)."""
    # Un solo partido: ARG-BRA
    matches_1 = MATCHES_BASE.iloc[:1].copy()
    as_of = "2026-06-05"
    k = 5

    rates, mu_global = count_rates(matches_1, as_of, stat, k=k)

    # mu_global debe ser > 0 (hay datos)
    assert mu_global > 0.0, f"[{stat}] mu_global debe ser positivo, got {mu_global}"

    # ARG tiene n=1 partido; con k=5 su tasa debe estar entre mu_global y raw_att
    assert "ARG" in rates, f"[{stat}] ARG debe aparecer en rates"
    arg_att = rates["ARG"]["att"]
    assert rates["ARG"]["n"] == 1, f"[{stat}] n esperado 1, got {rates['ARG']['n']}"

    # Con n=1 y k=5, el shrinkage tira hacia mu_global: att != raw_att puro
    # Verificamos que no sea exactamente el raw (el shrinkage modifica el valor)
    spec = STAT_SPECS[stat]
    home_col = f"home_{spec.silver_col_base}"
    raw_att = float(matches_1.iloc[0][home_col])

    # shrinkage: att = (1*raw + 5*mu) / 6 → entre mu y raw
    expected_att = (1.0 * raw_att + 5.0 * mu_global) / 6.0
    assert abs(arg_att - expected_att) < 1e-9, (
        f"[{stat}] att esperado {expected_att:.4f}, got {arg_att:.4f}"
    )

    # Con n bajo, la tasa debe estar entre mu_global y raw_att (tirar al prior)
    lo, hi = min(mu_global, raw_att), max(mu_global, raw_att)
    assert lo <= arg_att <= hi, (
        f"[{stat}] att={arg_att:.4f} debe estar en [{lo:.4f}, {hi:.4f}]"
    )


# ---------------------------------------------------------------------------
# R1 — test_anti_fuga_as_of
# ---------------------------------------------------------------------------


def test_anti_fuga_as_of() -> None:
    """Partidos con date >= as_of NO deben contribuir a las tasas (R1)."""
    # as_of = 2026-06-02: solo el primer partido (2026-06-01) queda incluido
    as_of_early = "2026-06-02"

    for stat in ("cards", "shots", "sot"):
        rates_early, mu_early = count_rates(MATCHES_BASE, as_of_early, stat)
        rates_all, mu_all = count_rates(MATCHES_BASE, _AS_OF, stat)

        # Con as_of temprano, menos datos => distintas tasas
        assert mu_early > 0.0, f"[{stat}] mu_early debe ser > 0"
        assert mu_all > 0.0, f"[{stat}] mu_all debe ser > 0"

        # Con un solo partido, teams son solo ARG y BRA; no debe haber MEX, USA, CAN
        assert "MEX" not in rates_early, f"[{stat}] MEX no debe aparecer con as_of={as_of_early}"
        assert "USA" not in rates_early, f"[{stat}] USA no debe aparecer con as_of={as_of_early}"

        # Con todos los partidos, MEX debe aparecer
        assert "MEX" in rates_all, f"[{stat}] MEX debe aparecer con as_of={_AS_OF}"


# ---------------------------------------------------------------------------
# R1 — test_stat_ausente_degrada
# ---------------------------------------------------------------------------


def test_stat_ausente_degrada() -> None:
    """Sin columnas de la stat en el silver, count_rates devuelve ({}, 0.0) (R1)."""
    # Silver solo con corners (sin cards/shots/sot)
    matches_sin_stat = pd.DataFrame(
        [
            {"date": "2026-06-01", "home_code": "ARG", "away_code": "BRA",
             "home_corners": 10.0, "away_corners": 5.0},
        ]
    )

    for stat in ("cards", "shots", "sot"):
        rates, mu = count_rates(matches_sin_stat, _AS_OF, stat)
        assert rates == {}, f"[{stat}] rates debe ser vacío sin columnas, got {rates}"
        assert mu == 0.0, f"[{stat}] mu debe ser 0.0 sin columnas, got {mu}"


def test_stat_ausente_summary_mu_cero() -> None:
    """count_summary con columnas ausentes devuelve mu_global=0.0 (degradacion, R1)."""
    matches_sin_stat = pd.DataFrame(
        [
            {"date": "2026-06-01", "home_code": "ARG", "away_code": "BRA",
             "home_corners": 10.0, "away_corners": 5.0},
        ]
    )
    for stat in ("cards", "shots", "sot"):
        cs = count_summary(matches_sin_stat, "ARG", "BRA", _AS_OF, stat)
        assert cs.mu_global == 0.0, (
            f"[{stat}] mu_global debe ser 0.0 con columnas ausentes, got {cs.mu_global}"
        )
        # Lambdas triviales (> 0 por clip defensivo)
        assert cs.lambda_home > 0.0
        assert cs.lambda_away > 0.0


# ---------------------------------------------------------------------------
# R2 — test_over_under_poisson_suma_uno_por_stat
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stat", ["cards", "shots", "sot"])
def test_over_under_poisson_suma_uno_por_stat(stat: str) -> None:
    """over + under = 1.0 para cada linea, total y por equipo, para cada stat (R2)."""
    cs = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, stat)

    # Total O/U
    for ou in cs.total_ou:
        total = ou.over + ou.under
        assert abs(total - 1.0) < 1e-9, (
            f"[{stat}] total O/U: over+under={total:.10f} para linea {ou.line}"
        )

    # Home O/U
    for ou in cs.home_ou:
        total = ou.over + ou.under
        assert abs(total - 1.0) < 1e-9, (
            f"[{stat}] home O/U: over+under={total:.10f} para linea {ou.line}"
        )

    # Away O/U
    for ou in cs.away_ou:
        total = ou.over + ou.under
        assert abs(total - 1.0) < 1e-9, (
            f"[{stat}] away O/U: over+under={total:.10f} para linea {ou.line}"
        )


# ---------------------------------------------------------------------------
# R2 — test_lineas_default_por_stat
# ---------------------------------------------------------------------------


def test_lineas_default_por_stat() -> None:
    """Cada stat usa sus lineas default correctas de STAT_SPECS (R2)."""
    for stat, expected_lines in [
        ("cards", (2.5, 3.5, 4.5)),
        ("shots", (20.5, 24.5, 28.5)),
        ("sot", (6.5, 8.5, 10.5)),
    ]:
        cs = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, stat)
        actual_lines = tuple(ou.line for ou in cs.total_ou)
        assert actual_lines == expected_lines, (
            f"[{stat}] lineas esperadas {expected_lines}, got {actual_lines}"
        )


def test_lineas_custom() -> None:
    """Con CountConfig.lines custom, count_summary usa esas lineas (R2)."""
    config = CountConfig(k=5, lines=(1.5, 2.5))
    cs = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, "cards", config)
    actual_lines = tuple(ou.line for ou in cs.total_ou)
    assert actual_lines == (1.5, 2.5), f"lineas custom esperadas (1.5, 2.5), got {actual_lines}"


# ---------------------------------------------------------------------------
# R4 — test_app_mercados_incluye_stats_o_degrada
# (Verifica la logica pura: count_summary con/sin datos => resultado coherente)
# ---------------------------------------------------------------------------


def test_app_mercados_incluye_stats_o_degrada() -> None:
    """Con datos presentes, count_summary retorna mu>0 y O/U validos; sin datos, degrada (R4)."""
    # Con datos
    for stat in ("cards", "shots", "sot"):
        cs = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, stat)
        assert cs.mu_global > 0.0, f"[{stat}] con datos: mu_global debe ser > 0"
        assert len(cs.total_ou) > 0, f"[{stat}] con datos: total_ou no puede ser vacio"
        assert cs.n_matches_home > 0, f"[{stat}] ARG debe tener partidos"

    # Sin datos (silver vacio)
    matches_vacios = pd.DataFrame(
        [{"date": "2026-06-01", "home_code": "ARG", "away_code": "BRA"}]
    )
    for stat in ("cards", "shots", "sot"):
        cs = count_summary(matches_vacios, "ARG", "BRA", _AS_OF, stat)
        assert cs.mu_global == 0.0, (
            f"[{stat}] sin datos: mu_global debe ser 0.0, got {cs.mu_global}"
        )


# ---------------------------------------------------------------------------
# R4 — test_tarjetas_lleva_aviso_ruido
# ---------------------------------------------------------------------------


def test_tarjetas_lleva_aviso_ruido() -> None:
    """El CountSummary de 'cards' tiene noisy_note no-None; shots y sot tienen None (R4)."""
    cs_cards = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, "cards")
    assert cs_cards.noisy_note is not None, (
        "cards: noisy_note debe ser no-None (advertencia de ruido por arbitro)"
    )
    assert "arbitro" in cs_cards.noisy_note.lower() or "ruido" in cs_cards.noisy_note.lower(), (
        f"cards: noisy_note debe mencionar 'arbitro' o 'ruido', got: {cs_cards.noisy_note!r}"
    )

    cs_shots = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, "shots")
    assert cs_shots.noisy_note is None, (
        f"shots: noisy_note debe ser None, got {cs_shots.noisy_note!r}"
    )

    cs_sot = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, "sot")
    assert cs_sot.noisy_note is None, (
        f"sot: noisy_note debe ser None, got {cs_sot.noisy_note!r}"
    )


# ---------------------------------------------------------------------------
# R5 — Determinismo: mismos inputs => mismos outputs (transversal)
# ---------------------------------------------------------------------------


def test_determinismo_count_summary() -> None:
    """count_summary es determinista: mismos inputs => exactamente mismos outputs (R5)."""
    for stat in ("cards", "shots", "sot"):
        cs1 = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, stat)
        cs2 = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, stat)
        assert cs1 == cs2, f"[{stat}] count_summary no es determinista"


def test_n_matches_en_summary() -> None:
    """n_matches_home/away refleja el numero de partidos que sustentan la estimacion (R5)."""
    for stat in ("cards", "shots", "sot"):
        cs = count_summary(MATCHES_BASE, "ARG", "BRA", _AS_OF, stat)
        # ARG tiene 3 partidos en MATCHES_BASE (2 home + 1 away)
        assert cs.n_matches_home == 3, (
            f"[{stat}] ARG: n_matches_home=3 esperado, got {cs.n_matches_home}"
        )
        # BRA tiene 2 partidos (1 home + 1 away)
        assert cs.n_matches_away == 2, (
            f"[{stat}] BRA: n_matches_away=2 esperado, got {cs.n_matches_away}"
        )


def test_shrinkage_k_cero_sin_prior() -> None:
    """Con k=0 (sin shrinkage), la tasa es la media cruda del equipo (R5)."""
    # Un partido: ARG-BRA, home_cards=3, away_cards=2
    matches_1 = MATCHES_BASE.iloc[:1].copy()
    as_of = "2026-06-05"

    rates, mu_global = count_rates(matches_1, as_of, "cards", k=0)

    # Con k=0: att = (1*raw + 0*mu) / 1 = raw_att
    assert "ARG" in rates
    expected_att_arg = 3.0  # ARG fue home con 3 tarjetas
    assert abs(rates["ARG"]["att"] - expected_att_arg) < 1e-9, (
        f"k=0: att ARG esperado {expected_att_arg}, got {rates['ARG']['att']}"
    )


def test_expected_counts_equipo_no_visto() -> None:
    """Equipo no visto en rates -> usa mu_global como tasa (factor neutro) (R5)."""
    rates, mu_global = count_rates(MATCHES_BASE, _AS_OF, "cards")
    # URU no aparece en MATCHES_BASE
    lam_h, lam_a, lam_t = expected_counts(rates, "URU", "ARG", mu_global)
    # lambda_home = mu_global * 1.0 * (dfn_ARG / mu_global) = dfn_ARG
    assert lam_h > 0.0
    assert lam_a > 0.0
    assert abs(lam_t - (lam_h + lam_a)) < 1e-9


def test_count_over_under_suma_uno() -> None:
    """count_over_under: over+under=1.0 para cada linea (R2, R5)."""
    for lam in (1.0, 3.5, 10.0, 25.0):
        for lines in ((2.5, 3.5, 4.5), (20.5, 24.5, 28.5), (6.5, 8.5, 10.5)):
            result = count_over_under(lam, lines)
            for line, vals in result.items():
                total = vals["over"] + vals["under"]
                assert abs(total - 1.0) < 1e-9, (
                    f"lam={lam}, line={line}: over+under={total:.10f}"
                )


def test_stat_specs_claves() -> None:
    """STAT_SPECS tiene exactamente las claves 'cards', 'shots', 'sot' (R5)."""
    assert set(STAT_SPECS.keys()) == {"cards", "shots", "sot"}, (
        f"STAT_SPECS.keys() incorrecto: {set(STAT_SPECS.keys())}"
    )
