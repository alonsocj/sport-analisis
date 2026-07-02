"""Tests del modelo de corners O/U (Feature 24: R1-R3, R5, R6).

Todos offline: sin red, sin modelo entrenado, sin archivos de produccion.
Los fixtures de silver son DataFrames construidos en memoria.

Trazabilidad (tasks.md):
  R1 <- test_shrinkage_tira_a_global_con_n_bajo
         test_anti_fuga_as_of
         test_equipo_sin_datos_prior_global
  R2 <- test_expected_corners_combina_ataque_defensa
  R3 <- test_over_under_poisson_suma_uno
         test_lineas_por_equipo
  R5 <- test_app_mercados_incluye_corners_o_degrada
  R6 <- test_determinismo (offline, as_of inyectado, sin libs nuevas)
        test_n_matches_en_summary (aviso de muestra)
        test_shrinkage_k_es_configurable (prior global con k alto)
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.markets.corners import (
    CornersConfig,
    CornersSummary,
    corners_over_under,
    corners_summary,
    expected_corners,
    team_corner_rates,
)


# ---------------------------------------------------------------------------
# Fixture base: 6 partidos, corners siempre presentes
# ARG: 3 partidos  (home 2x, away 1x)
# BRA: 2 partidos  (home 1x, away 1x)
# ---------------------------------------------------------------------------

MATCHES_BASE = pd.DataFrame(
    [
        # home,  away,  hc, ac,   date
        {"date": "2026-06-01", "home_code": "ARG", "away_code": "BRA", "home_corners": 11.0, "away_corners": 4.0},
        {"date": "2026-06-02", "home_code": "MEX", "away_code": "ARG", "home_corners": 5.0,  "away_corners": 12.0},
        {"date": "2026-06-03", "home_code": "ARG", "away_code": "USA", "home_corners": 10.0, "away_corners": 3.0},
        {"date": "2026-06-04", "home_code": "BRA", "away_code": "MEX", "home_corners": 7.0,  "away_corners": 6.0},
        {"date": "2026-06-05", "home_code": "USA", "away_code": "CAN", "home_corners": 5.0,  "away_corners": 8.0},
        {"date": "2026-06-06", "home_code": "MEX", "away_code": "CAN", "home_corners": 6.0,  "away_corners": 5.0},
    ]
)

AS_OF = "2026-06-10"  # todos los partidos anteriores quedan incluidos


# ---------------------------------------------------------------------------
# R1 — Shrinkage tira a la media global cuando n es bajo
# ---------------------------------------------------------------------------


def test_shrinkage_tira_a_global_con_n_bajo() -> None:
    """Con n=1 y k=5, la tasa de att de ARG debe estar entre raw_mean y mu_global (R1)."""
    # Fixture minimo: 1 solo partido ARG-BRA
    matches_1 = pd.DataFrame(
        [{"date": "2026-06-01", "home_code": "ARG", "away_code": "BRA",
          "home_corners": 11.0, "away_corners": 4.0}]
    )
    as_of = "2026-06-05"
    k = 5

    rates, mu_global = team_corner_rates(matches_1, as_of, k=k)

    # mu_global = (11 + 4) / 2 = 7.5
    assert abs(mu_global - 7.5) < 1e-9, f"mu_global esperado 7.5, got {mu_global}"

    # ARG tiene n=1 partido; att raw = 11.0 (home corners)
    # lambda_att = (1*11 + 5*7.5) / (1+5) = 48.5/6 ≈ 8.083
    arg_att = rates["ARG"]["att"]
    raw_att = 11.0
    # Con shrinkage, att debe estar entre mu_global y raw_att (no domina el raw)
    assert mu_global < arg_att < raw_att, (
        f"Shrinkage fallo: mu={mu_global}, att_shrinkage={arg_att}, raw={raw_att}. "
        "Con n bajo, la tasa debe quedar entre el prior global y la media cruda."
    )

    # Oracle: (1*11 + 5*7.5) / 6 = 8.08333...
    expected_att = (1 * 11.0 + 5 * 7.5) / (1 + 5)
    assert abs(arg_att - expected_att) < 1e-9, (
        f"Formula shrinkage incorrecta: esperado {expected_att}, got {arg_att}"
    )


# ---------------------------------------------------------------------------
# R1 — Anti-fuga: solo date < as_of
# ---------------------------------------------------------------------------


def test_anti_fuga_as_of() -> None:
    """Partido con date >= as_of NO debe contaminar las tasas (R1)."""
    # Partido legitimo + partido con 99 corners que queda FUERA del corte
    matches = pd.DataFrame(
        [
            {"date": "2026-06-01", "home_code": "ARG", "away_code": "BRA",
             "home_corners": 6.0, "away_corners": 6.0},
            # Este partido debe quedar EXCLUIDO (date = as_of, no estrictamente menor)
            {"date": "2026-06-10", "home_code": "ARG", "away_code": "BRA",
             "home_corners": 99.0, "away_corners": 99.0},
        ]
    )
    as_of = "2026-06-10"

    rates, mu_global = team_corner_rates(matches, as_of, k=0)  # k=0 = sin shrinkage

    # Sin fuga: solo el partido del 06-01 debe contar
    # ARG att = 6, dfn = 6; mu_global = 6
    assert abs(mu_global - 6.0) < 1e-9, (
        f"Fuga detectada: mu_global={mu_global} != 6.0. "
        "El partido con date=as_of no debe incluirse."
    )
    assert abs(float(rates["ARG"]["att"]) - 6.0) < 1e-9, (
        f"Fuga en att ARG: {rates['ARG']['att']} != 6.0"
    )


# ---------------------------------------------------------------------------
# R1 — Equipo sin datos => prior global como fallback
# ---------------------------------------------------------------------------


def test_equipo_sin_datos_prior_global() -> None:
    """Equipo no visto en silver => expected_corners usa mu_global como tasa (R1)."""
    rates, mu_global = team_corner_rates(MATCHES_BASE, AS_OF, k=5)

    # RSA no aparece en ningun partido de MATCHES_BASE
    assert "RSA" not in rates, "RSA no deberia estar en rates"

    # ARG si tiene datos
    arg_att = float(rates["ARG"]["att"])
    arg_dfn = float(rates["ARG"]["dfn"])

    # ARG vs RSA (RSA desconocido => usa mu_global como att y dfn)
    # lambda_home = att_ARG * dfn_RSA / mu_global = att_ARG * mu_global / mu_global = att_ARG
    lam_h, lam_a, _ = expected_corners(rates, "ARG", "RSA", mu_global)
    assert abs(lam_h - arg_att) < 1e-9, (
        f"lambda_home para RSA desconocido deberia == att_ARG={arg_att}, got {lam_h}"
    )

    # RSA vs ARG: lambda_home = att_RSA * dfn_ARG / mu = mu * dfn_ARG / mu = dfn_ARG
    lam_h2, lam_a2, _ = expected_corners(rates, "RSA", "ARG", mu_global)
    assert abs(lam_h2 - arg_dfn) < 1e-9, (
        f"lambda_home RSA desconocido vs ARG deberia == dfn_ARG={arg_dfn}, got {lam_h2}"
    )


# ---------------------------------------------------------------------------
# R2 — expected_corners combina ataque local y defensa visitante
# ---------------------------------------------------------------------------


def test_expected_corners_combina_ataque_defensa() -> None:
    """lambda_home = att_home * dfn_away / mu_global (R2). Oracle manual."""
    # Tasas sinteticas sin shrinkage (k=0) para oracle exacto
    matches_simple = pd.DataFrame(
        [
            {"date": "2026-06-01", "home_code": "A", "away_code": "B",
             "home_corners": 10.0, "away_corners": 4.0},
        ]
    )
    rates, mu_global = team_corner_rates(matches_simple, "2026-07-01", k=0)

    # A: att=10 (home corners cuando es local), dfn=4 (away corners concedidos)
    # B: att=4 (away corners cuando es visitante), dfn=10 (home corners concedidos al rival)
    # mu_global = (10+4)/2 = 7.0
    assert abs(mu_global - 7.0) < 1e-9

    att_A = float(rates["A"]["att"])  # 10.0
    dfn_A = float(rates["A"]["dfn"])  # 4.0
    att_B = float(rates["B"]["att"])  # 4.0
    dfn_B = float(rates["B"]["dfn"])  # 10.0

    lam_h, lam_a, lam_t = expected_corners(rates, "A", "B", mu_global)

    expected_h = att_A * dfn_B / mu_global  # 10 * 10 / 7 = 14.2857
    expected_a = att_B * dfn_A / mu_global  # 4 * 4 / 7 = 2.2857

    assert abs(lam_h - expected_h) < 1e-9, (
        f"lambda_home: esperado {expected_h:.6f}, got {lam_h:.6f}"
    )
    assert abs(lam_a - expected_a) < 1e-9, (
        f"lambda_away: esperado {expected_a:.6f}, got {lam_a:.6f}"
    )
    assert abs(lam_t - (expected_h + expected_a)) < 1e-9, (
        "lambda_total != lambda_home + lambda_away"
    )


# ---------------------------------------------------------------------------
# R3 — over + under = 1 por linea (Poisson CDF bien construido)
# ---------------------------------------------------------------------------


def test_over_under_poisson_suma_uno() -> None:
    """Para cada linea, over + under == 1.0 exactamente (R3)."""
    lines = (8.5, 9.5, 10.5, 11.5, 6.5)
    lam = 9.0

    result = corners_over_under(lam, lines)

    for line in lines:
        over = result[line]["over"]
        under = result[line]["under"]
        # under = 1 - over por construccion, debe ser exactamente 1.0
        total = over + under
        assert total == 1.0, (
            f"Linea {line}: over={over} + under={under} = {total} != 1.0"
        )
        assert 0.0 <= over <= 1.0, f"Linea {line}: over={over} fuera de [0, 1]"
        assert 0.0 <= under <= 1.0, f"Linea {line}: under={under} fuera de [0, 1]"


def test_over_under_poisson_monotonia() -> None:
    """P(over) decrece estrictamente al subir la linea para lambda fijo (R3)."""
    lines = (6.5, 7.5, 8.5, 9.5, 10.5, 11.5)
    lam = 9.5

    result = corners_over_under(lam, sorted(lines))
    overs = [result[ln]["over"] for ln in sorted(lines)]

    for i in range(len(overs) - 1):
        assert overs[i] > overs[i + 1], (
            f"Monotonia rota: P(over {sorted(lines)[i]}) = {overs[i]} <= "
            f"P(over {sorted(lines)[i+1]}) = {overs[i+1]}"
        )


# ---------------------------------------------------------------------------
# R3 — corners_summary expone O/U total, home y away
# ---------------------------------------------------------------------------


def test_lineas_por_equipo() -> None:
    """corners_summary expone total_ou, home_ou y away_ou con las lineas correctas (R3)."""
    config = CornersConfig(k=5, default_lines=(8.5, 9.5, 10.5))
    summary = corners_summary(MATCHES_BASE, "ARG", "BRA", AS_OF, config)

    lines_expected = frozenset({8.5, 9.5, 10.5})

    assert frozenset(ou.line for ou in summary.total_ou) == lines_expected, (
        f"total_ou lines: esperado {lines_expected}, got "
        f"{frozenset(ou.line for ou in summary.total_ou)}"
    )
    assert frozenset(ou.line for ou in summary.home_ou) == lines_expected, (
        "home_ou lines no coinciden con las configuradas"
    )
    assert frozenset(ou.line for ou in summary.away_ou) == lines_expected, (
        "away_ou lines no coinciden con las configuradas"
    )

    # over + under == 1 en cada sub-coleccion
    for collection in (summary.total_ou, summary.home_ou, summary.away_ou):
        for ou in collection:
            assert ou.over + ou.under == 1.0, (
                f"over + under != 1.0 en linea {ou.line}: {ou.over} + {ou.under}"
            )


# ---------------------------------------------------------------------------
# R5 — App: _compute_corners_data incluye corners o degrada
# ---------------------------------------------------------------------------


def test_app_mercados_incluye_corners_o_degrada(tmp_path: pytest.TempdirFactory) -> None:
    """_compute_corners_data devuelve summary con datos o degrada con error (R5)."""
    from src.app.tabs.knockouts import _compute_corners_data

    _compute_corners_data.clear()

    # Caso 1: silver con corners → debe devolver summary
    silver_with = tmp_path / "silver_with.csv"
    MATCHES_BASE.to_csv(silver_with, index=False)

    result = _compute_corners_data("ARG", "BRA", str(silver_with), AS_OF, k=5)
    assert result["error"] is None, (
        f"Con datos de corners esperamos error=None, got {result['error']!r}"
    )
    cs = result["summary"]
    assert isinstance(cs, CornersSummary), "summary debe ser CornersSummary"
    assert cs.lambda_total > 0, "lambda_total debe ser > 0 con datos reales"

    _compute_corners_data.clear()

    # Caso 2: silver sin columnas de corners (solo goles) → debe degradar
    silver_no_corners = tmp_path / "silver_no_corners.csv"
    pd.DataFrame(
        [{"date": "2026-06-01", "home_code": "ARG", "away_code": "BRA"}]
    ).to_csv(silver_no_corners, index=False)

    result2 = _compute_corners_data("ARG", "BRA", str(silver_no_corners), AS_OF, k=5)
    assert result2["summary"] is None, (
        "Sin columnas de corners, summary debe ser None (degradacion)"
    )
    assert result2["error"] is not None, (
        "Sin columnas de corners, error debe ser no-None"
    )

    _compute_corners_data.clear()

    # Caso 3: silver inexistente → degrada con error
    result3 = _compute_corners_data("ARG", "BRA", str(tmp_path / "noexiste.csv"), AS_OF)
    assert result3["summary"] is None
    assert result3["error"] == "no_silver"

    _compute_corners_data.clear()


# ---------------------------------------------------------------------------
# R6 — Determinismo
# ---------------------------------------------------------------------------


def test_determinismo() -> None:
    """Mismos inputs => mismos outputs (sin RNG, offline, R6)."""
    config = CornersConfig(k=5, default_lines=(9.5, 10.5))

    s1 = corners_summary(MATCHES_BASE, "ARG", "BRA", AS_OF, config)
    s2 = corners_summary(MATCHES_BASE, "ARG", "BRA", AS_OF, config)

    assert s1.lambda_home == s2.lambda_home
    assert s1.lambda_away == s2.lambda_away
    assert s1.mu_global == s2.mu_global
    assert s1.total_ou == s2.total_ou


# ---------------------------------------------------------------------------
# R6 — n_matches en el summary (aviso de muestra chica)
# ---------------------------------------------------------------------------


def test_n_matches_en_summary() -> None:
    """corners_summary reporta n_matches_home y n_matches_away correctamente (R6)."""
    # MATCHES_BASE: ARG en 3 partidos, BRA en 2 partidos (ver fixture)
    summary = corners_summary(MATCHES_BASE, "ARG", "BRA", AS_OF)

    assert summary.n_matches_home == 3, (
        f"ARG deberia tener n=3, got {summary.n_matches_home}"
    )
    assert summary.n_matches_away == 2, (
        f"BRA deberia tener n=2, got {summary.n_matches_away}"
    )


# ---------------------------------------------------------------------------
# R6 — k configurable cambia los lambdas
# ---------------------------------------------------------------------------


def test_shrinkage_k_es_configurable() -> None:
    """k=0 (sin prior) vs k=100 (full prior) produce lambdas distintos (R6)."""
    # Solo 1 partido para que la diferencia sea maxima
    matches_1 = pd.DataFrame(
        [{"date": "2026-06-01", "home_code": "ARG", "away_code": "BRA",
          "home_corners": 20.0, "away_corners": 2.0}]
    )

    s_k0 = corners_summary(matches_1, "ARG", "BRA", "2026-07-01", CornersConfig(k=0))
    s_k100 = corners_summary(matches_1, "ARG", "BRA", "2026-07-01", CornersConfig(k=100))

    # Con k=0 no hay shrinkage: ARG att = 20, BRA att = 2 => lambdas muy distintos
    # Con k=100 total prior: ARG att -> mu_global = (20+2)/2 = 11 => lambdas cercanos
    assert s_k0.lambda_home != s_k100.lambda_home, (
        "k=0 y k=100 deberian producir lambda_home distintos"
    )
    # k=100 tira a prior: lambda_home debe ser mas cercano a mu_global
    mu = s_k0.mu_global
    dist_k0 = abs(s_k0.lambda_home - mu)
    dist_k100 = abs(s_k100.lambda_home - mu)
    assert dist_k100 < dist_k0, (
        f"k=100 deberia acercar lambda a mu_global ({mu:.2f}): "
        f"dist_k0={dist_k0:.3f}, dist_k100={dist_k100:.3f}"
    )
