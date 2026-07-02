"""Tests del sub-modelo Elo→1X2 y del ensemble — Feature 14, R3, R4, R5, R6, R7, R9.

Cubre:
- R3: artefacto gold determinista
- R4: sub-modelo Elo→1X2 con oráculo y neutral
- R5: ensemble w=0 idéntico a DC (tol 1e-9); ensemble mezcla y renormaliza
- R6: ajuste w por backtest reproducible
- R7: anti-fuga as-of; Elo externo rechazado en backtest
- R9: sin reloj, determinista

Todos offline; no usa red.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers de fixture: elo_history mínimo para tests
# ---------------------------------------------------------------------------


def _make_elo_history() -> pd.DataFrame:
    """Historial Elo mínimo con 4 filas para tests de as-of."""
    return pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-01", "2026-03-01", "2026-03-01"],
            "code": ["ESP", "FRA", "ESP", "BRA"],
            "opponent_code": ["FRA", "ESP", "BRA", "ESP"],
            "elo_pre": [2000.0, 1900.0, 2010.0, 1850.0],
            "elo_post": [2010.0, 1890.0, 2020.0, 1840.0],
            "k": [60.0, 60.0, 60.0, 60.0],
            "g": [1.0, 1.0, 1.0, 1.0],
            "we": [0.6, 0.4, 0.7, 0.3],
            "score": [1.0, 0.0, 1.0, 0.0],
        }
    )


def _make_dc_predictions() -> list:
    """Lista mínima de WindowPrediction para tests de ensemble."""
    from src.backtest.walkforward import WindowPrediction

    return [
        WindowPrediction(
            date="2026-04-01",
            home_code="ESP",
            away_code="FRA",
            prob_home=0.50,
            prob_draw=0.25,
            prob_away=0.25,
            actual="1",
            marginal_home=0.45,
            marginal_draw=0.27,
            marginal_away=0.28,
        ),
        WindowPrediction(
            date="2026-04-15",
            home_code="BRA",
            away_code="ESP",
            prob_home=0.40,
            prob_draw=0.30,
            prob_away=0.30,
            actual="2",
            marginal_home=0.40,
            marginal_draw=0.30,
            marginal_away=0.30,
        ),
        WindowPrediction(
            date="2026-05-01",
            home_code="FRA",
            away_code="BRA",
            prob_home=0.45,
            prob_draw=0.28,
            prob_away=0.27,
            actual="X",
            marginal_home=0.42,
            marginal_draw=0.28,
            marginal_away=0.30,
        ),
    ]


# ---------------------------------------------------------------------------
# R4 — sub-modelo Elo→1X2
# ---------------------------------------------------------------------------


def test_elo_a_1x2_oraculo_y_neutral() -> None:
    """R4: fórmula Elo→1X2 con oráculo verificado y diferencia entre neutral/no-neutral."""
    from src.elo_ext.model import elo_to_1x2, EloModelParams

    params = EloModelParams(home_advantage=100.0, draw_param=0.3, elo_scale=400.0)

    # Equipos iguales, neutral: E=0.5 → p_home = p_away, p_draw máximo
    probs_neutral = elo_to_1x2(1500.0, 1500.0, neutral=True, params=params)
    assert abs(probs_neutral.prob_home - probs_neutral.prob_away) < 1e-10
    assert probs_neutral.prob_draw > 0.0

    # Equipos iguales, no neutral: ventaja local → p_home > p_away
    probs_home = elo_to_1x2(1500.0, 1500.0, neutral=False, params=params)
    assert probs_home.prob_home > probs_home.prob_away

    # Suman 1
    total = probs_home.prob_home + probs_home.prob_draw + probs_home.prob_away
    assert abs(total - 1.0) < 1e-10

    # Oráculo: ΔElo=200 neutral=True → E ≈ 1/(1+10^(-200/400)) = 1/(1+10^(-0.5))
    import math
    e_oracle = 1.0 / (1.0 + 10.0 ** (-200.0 / 400.0))
    p_draw_oracle = 0.3 * (1.0 - abs(2.0 * e_oracle - 1.0))
    p_home_oracle = e_oracle * (1.0 - p_draw_oracle)
    p_away_oracle = (1.0 - e_oracle) * (1.0 - p_draw_oracle)
    total_oracle = p_home_oracle + p_draw_oracle + p_away_oracle

    probs_200 = elo_to_1x2(1700.0, 1500.0, neutral=True, params=params)
    assert abs(probs_200.prob_home - p_home_oracle / total_oracle) < 1e-10
    assert abs(probs_200.prob_draw - p_draw_oracle / total_oracle) < 1e-10
    assert abs(probs_200.prob_away - p_away_oracle / total_oracle) < 1e-10


def test_elo_probs_siempre_positivas() -> None:
    """R4: probabilidades 1X2 siempre > 0 para cualquier diferencia Elo razonable."""
    from src.elo_ext.model import elo_to_1x2

    for delta in [-500, -200, 0, 200, 500]:
        probs = elo_to_1x2(1500.0 + delta, 1500.0, neutral=True)
        assert probs.prob_home > 0.0
        assert probs.prob_draw >= 0.0
        assert probs.prob_away > 0.0
        total = probs.prob_home + probs.prob_draw + probs.prob_away
        assert abs(total - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# R5 — ensemble w=0 idéntico a DC (no-regresión v1)
# ---------------------------------------------------------------------------


def test_ensemble_w0_equivale_dc() -> None:
    """R5: ensemble con w=0 reproduce p_DC EXACTAMENTE (tol 1e-9). No-regresión v1."""
    from src.elo_ext.ensemble import ensemble
    from src.elo_ext.model import EloProbs

    p_dc = (0.5237, 0.2641, 0.2122)
    p_elo = EloProbs(prob_home=0.60, prob_draw=0.20, prob_away=0.20)

    result = ensemble(p_dc, p_elo, w=0.0)

    assert abs(result.prob_home - p_dc[0]) < 1e-9
    assert abs(result.prob_draw - p_dc[1]) < 1e-9
    assert abs(result.prob_away - p_dc[2]) < 1e-9


def test_ensemble_mezcla_y_renormaliza() -> None:
    """R5: ensemble con w>0 mezcla y renormaliza a 1."""
    from src.elo_ext.ensemble import ensemble
    from src.elo_ext.model import EloProbs

    p_dc = (0.50, 0.25, 0.25)
    p_elo = EloProbs(prob_home=0.70, prob_draw=0.15, prob_away=0.15)

    for w in (0.1, 0.3, 0.5):
        result = ensemble(p_dc, p_elo, w=w)
        total = result.prob_home + result.prob_draw + result.prob_away
        assert abs(total - 1.0) < 1e-10
        # Verificar que la mezcla va en la dirección correcta
        if w > 0:
            assert result.prob_home > p_dc[0]  # Elo da más al local


def test_ensemble_w_invalido() -> None:
    """R5: w fuera de [0,1] → ValueError."""
    from src.elo_ext.ensemble import ensemble
    from src.elo_ext.model import EloProbs

    p_dc = (0.50, 0.25, 0.25)
    p_elo = EloProbs(prob_home=0.60, prob_draw=0.20, prob_away=0.20)

    with pytest.raises(ValueError, match="peso w"):
        ensemble(p_dc, p_elo, w=-0.1)

    with pytest.raises(ValueError, match="peso w"):
        ensemble(p_dc, p_elo, w=1.1)


# ---------------------------------------------------------------------------
# R6 — ajuste de w por backtest reproducible
# ---------------------------------------------------------------------------


def test_ajuste_w_por_backtest_reproducible() -> None:
    """R6: el ajuste de w/d por backtest es reproducible (misma entrada → mismo resultado)."""
    from src.elo_ext.ensemble import adjust_ensemble_weights, W_GRID, D_GRID

    history = _make_elo_history()
    preds = _make_dc_predictions()

    result1 = adjust_ensemble_weights(preds, history, w_grid=W_GRID, d_grid=D_GRID)
    result2 = adjust_ensemble_weights(preds, history, w_grid=W_GRID, d_grid=D_GRID)

    assert result1.best_w == result2.best_w
    assert result1.best_d == result2.best_d
    assert abs(result1.best_log_loss - result2.best_log_loss) < 1e-12
    assert abs(result1.dc_log_loss - result2.dc_log_loss) < 1e-12


def test_ajuste_w_devuelve_dc_log_loss() -> None:
    """R6: dc_log_loss coincide con w=0 en la rejilla."""
    from src.elo_ext.ensemble import adjust_ensemble_weights, W_GRID, D_GRID

    history = _make_elo_history()
    preds = _make_dc_predictions()

    result = adjust_ensemble_weights(preds, history, w_grid=W_GRID, d_grid=D_GRID)

    # dc_log_loss debe ser el log-loss cuando w=0 (que está en la rejilla)
    # El resultado del grid con w=0 para cualquier d debe igualar dc_log_loss
    w0_rows = result.grid_results[result.grid_results["w"] == 0.0]
    assert not w0_rows.empty
    for ll in w0_rows["log_loss"]:
        assert abs(ll - result.dc_log_loss) < 1e-10


def test_ajuste_grid_cubre_todos_los_pares() -> None:
    """R6: el DataFrame de resultados cubre todos los pares (w, d) de la rejilla."""
    from src.elo_ext.ensemble import adjust_ensemble_weights, W_GRID, D_GRID

    history = _make_elo_history()
    preds = _make_dc_predictions()

    result = adjust_ensemble_weights(preds, history, w_grid=W_GRID, d_grid=D_GRID)

    expected_pairs = len(W_GRID) * len(D_GRID)
    assert len(result.grid_results) == expected_pairs


# ---------------------------------------------------------------------------
# R3 — artefacto gold determinista
# ---------------------------------------------------------------------------


def test_artefacto_gold_determinista(tmp_path: Path) -> None:
    """R3: misma entrada → mismo gold byte a byte (determinismo)."""
    from src.ingestion.elo_ratings import write_gold_external_elo

    mapped_rows = [
        {"team_code": "BRA", "elo": 2045},
        {"team_code": "ESP", "elo": 2090},
        {"team_code": "FRA", "elo": 2060},
    ]
    gold_1 = tmp_path / "gold_1.csv"
    gold_2 = tmp_path / "gold_2.csv"

    write_gold_external_elo(mapped_rows, "2026-06-17", gold_1)
    write_gold_external_elo(mapped_rows, "2026-06-17", gold_2)

    assert gold_1.read_bytes() == gold_2.read_bytes()


def test_artefacto_gold_ordenado_por_team_code(tmp_path: Path) -> None:
    """R3: gold ordenado por team_code (orden inverso al de entrada → se reordena)."""
    from src.ingestion.elo_ratings import write_gold_external_elo

    # Entrada en orden Z→A
    mapped_rows = [
        {"team_code": "USA", "elo": 1865},
        {"team_code": "FRA", "elo": 2060},
        {"team_code": "ARG", "elo": 2025},
    ]
    gold_path = tmp_path / "external_elo.csv"
    write_gold_external_elo(mapped_rows, "2026-06-17", gold_path)

    df = pd.read_csv(gold_path)
    assert list(df["team_code"]) == sorted(df["team_code"])


# ---------------------------------------------------------------------------
# R7 — anti-fuga as-of y rechazo del Elo externo en backtest
# ---------------------------------------------------------------------------


def test_anti_fuga_elo_as_of() -> None:
    """R7: el Elo as-of solo usa partidos con date < as_of_date (leak-free)."""
    from src.elo_ext.model import elo_from_history

    history = _make_elo_history()

    # As-of antes del primer partido: no hay historial → rating inicial
    elo_inicial = elo_from_history("ESP", as_of_date="2025-12-31", history=history)
    assert elo_inicial == 1500.0

    # As-of después del primer partido (2026-01-01): usa elo_post del 2026-01-01
    # El resultado del 2026-01-01 para ESP es elo_post=2010.0
    elo_post_jan = elo_from_history("ESP", as_of_date="2026-02-01", history=history)
    assert elo_post_jan == pytest.approx(2010.0, abs=1e-6)

    # As-of después del segundo partido (2026-03-01): usa elo_post del 2026-03-01
    # El resultado del 2026-03-01 para ESP es elo_post=2020.0
    elo_post_mar = elo_from_history("ESP", as_of_date="2026-04-01", history=history)
    assert elo_post_mar == pytest.approx(2020.0, abs=1e-6)

    # El Elo del 2026-03-01 NO debe usarse para predecir partidos del mismo día
    # as_of_date="2026-03-01" → solo usa date < "2026-03-01" → solo el 2026-01-01
    elo_same_day = elo_from_history("ESP", as_of_date="2026-03-01", history=history)
    assert elo_same_day == pytest.approx(2010.0, abs=1e-6)  # leak-free: no usa el 2026-03-01


def test_elo_externo_rechazado_en_backtest() -> None:
    """R7: use_external=True en predict_elo_backtest → EloExternoEnBacktestError."""
    from src.elo_ext.model import predict_elo_backtest, EloExternoEnBacktestError

    history = _make_elo_history()

    with pytest.raises(EloExternoEnBacktestError, match="fuga temporal"):
        predict_elo_backtest(
            home_code="ESP",
            away_code="FRA",
            as_of_date="2026-04-01",
            history=history,
            use_external=True,
        )


def test_elo_externo_ok_en_live(tmp_path: Path) -> None:
    """R7: predict_elo_live usa el Elo externo sin error (solo para live)."""
    from src.ingestion.elo_ratings import write_gold_external_elo
    from src.elo_ext.model import predict_elo_live

    # Crear un gold de external_elo con ESP y FRA
    mapped_rows = [
        {"team_code": "ESP", "elo": 2090},
        {"team_code": "FRA", "elo": 2060},
    ]
    gold_path = tmp_path / "external_elo.csv"
    write_gold_external_elo(mapped_rows, "2026-06-17", gold_path)

    probs = predict_elo_live("ESP", "FRA", neutral=True, external_elo_path=gold_path)
    assert abs(probs.prob_home + probs.prob_draw + probs.prob_away - 1.0) < 1e-10
    # ESP tiene Elo mayor → p_home ≥ p_away (neutral)
    assert probs.prob_home > probs.prob_away
