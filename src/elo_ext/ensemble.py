"""Ensemble Dixon-Coles + sub-modelo Elo → 1X2 (Feature 14, R5, R6).

Mezcla las probabilidades 1X2 del modelo Dixon-Coles (DC) con las del
sub-modelo Elo→1X2 mediante interpolación lineal a nivel de probabilidad:

    p_ensemble = (1 − w) · p_DC + w · p_Elo

donde ``w ∈ [0, 1]``. La mezcla se renormaliza para que sume exactamente 1.

Principio de no-regresión (R5):
    w = 0 → p_ensemble = p_DC EXACTO (tol 1e-9)

Ajuste de (w, d) por backtest walk-forward leak-free (R6):
    - Rejilla pequeña: w ∈ {0.0, 0.1, 0.2, 0.3, 0.4, 0.5}
    - Parámetro de empate d ∈ {0.1, 0.2, 0.3, 0.4} (EloModelParams.draw_param)
    - Para cada (w, d): calcula log-loss sobre las predicciones walk-forward
      usando elo_history as-of (leak-free, R7 — nunca Elo externo en backtest)
    - Devuelve el par (w, d) con menor log-loss y un DataFrame de resultados
    - Reporta DC (w=0) vs mejor ensemble de forma reproducible
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

from ..backtest.metrics import OUTCOME_ORDER, _SKLEARN_LABEL_ORDER, _SKL_COL_MAP
from ..backtest.walkforward import WindowPrediction
from .model import EloModelParams, EloProbs, predict_elo_backtest

# Rejilla de búsqueda (R6): diseñada para ser pequeña y reproducible
W_GRID: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
D_GRID: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4)


class EnsembleProbs(NamedTuple):
    """Probabilidades 1X2 del ensemble DC + Elo (R5)."""

    prob_home: float
    prob_draw: float
    prob_away: float


@dataclass(frozen=True)
class EnsembleResult:
    """Resultado del ajuste de (w, d) por backtest walk-forward (R6).

    Attributes:
        best_w: Peso óptimo del sub-modelo Elo en el ensemble.
        best_d: Parámetro de empate óptimo del sub-modelo Elo.
        best_log_loss: Log-loss del ensemble con best_w y best_d.
        dc_log_loss: Log-loss del DC puro (w=0), para comparación.
        grid_results: DataFrame con columnas w, d, log_loss (toda la rejilla).
    """

    best_w: float
    best_d: float
    best_log_loss: float
    dc_log_loss: float
    grid_results: pd.DataFrame


def ensemble(
    p_dc: EnsembleProbs | tuple[float, float, float],
    p_elo: EloProbs | tuple[float, float, float],
    w: float,
) -> EnsembleProbs:
    """Mezcla probabilidades DC y Elo con peso ``w`` (R5).

    ``p = (1−w)·p_DC + w·p_Elo``, renormalizado para que sume exactamente 1.
    Con ``w=0`` → ``p_DC`` EXACTO (tol 1e-9, test de equivalencia v1, R5).

    Args:
        p_dc: Tuple (prob_home, prob_draw, prob_away) from Dixon-Coles.
        p_elo: Tuple (prob_home, prob_draw, prob_away) from Elo sub-model.
        w: Blend weight for Elo; 0.0 = pure DC, 1.0 = pure Elo.

    Returns:
        EnsembleProbs renormalized to sum 1.

    Raises:
        ValueError: If w is not in [0, 1] or probabilities are invalid.
    """
    if not (0.0 <= w <= 1.0):
        raise ValueError(f"El peso w debe estar en [0, 1]; se recibió {w}")
    ph_dc, pd_dc, pa_dc = float(p_dc[0]), float(p_dc[1]), float(p_dc[2])
    ph_elo, pd_elo, pa_elo = float(p_elo[0]), float(p_elo[1]), float(p_elo[2])
    ph = (1.0 - w) * ph_dc + w * ph_elo
    pd_ = (1.0 - w) * pd_dc + w * pd_elo
    pa = (1.0 - w) * pa_dc + w * pa_elo
    total = ph + pd_ + pa
    if total <= 0.0:
        raise ValueError("La suma de probabilidades del ensemble es 0 o negativa")
    return EnsembleProbs(
        prob_home=ph / total,
        prob_draw=pd_ / total,
        prob_away=pa / total,
    )


def _log_loss_from_preds(
    preds: list[WindowPrediction],
) -> float:
    """Calcula log-loss sklearn sobre una lista de WindowPrediction (R6).

    Reutiliza el mismo orden de labels que el backtest propio (OUTCOME_ORDER).

    Args:
        preds: List of window predictions.

    Returns:
        Log-loss value (scalar float).
    """
    from sklearn.metrics import log_loss as _log_loss

    y_true = [p.actual for p in preds]
    probs_raw = np.array(
        [[p.prob_home, p.prob_draw, p.prob_away] for p in preds], dtype=float
    )
    # Reordenar al orden léxico que sklearn espera
    probs_skl = probs_raw[:, list(_SKL_COL_MAP)]
    return float(_log_loss(y_true, probs_skl, labels=list(_SKLEARN_LABEL_ORDER)))


def adjust_ensemble_weights(
    predictions_dc: list[WindowPrediction],
    elo_history: pd.DataFrame,
    w_grid: tuple[float, ...] = W_GRID,
    d_grid: tuple[float, ...] = D_GRID,
    initial_elo: float = 1500.0,
) -> EnsembleResult:
    """Ajusta (w, d) minimizando log-loss en backtest walk-forward leak-free (R6, R7).

    Para cada par (w, d) en la rejilla, calcula las probabilidades ensemble
    usando:
    - ``p_DC``: de las WindowPredictions del backtest DC (ya calculadas)
    - ``p_Elo``: del sub-modelo con elo_history as-of (date < fecha_partido, R7)
      NUNCA usa el Elo externo (snapshot eloratings) — garantiza anti-fuga (R7)

    La comparación DC vs ensemble es reproducible: usa las mismas predicciones.

    Args:
        predictions_dc: List of WindowPrediction from the DC backtest walk-forward.
        elo_history: Full elo_history DataFrame (columns: date, code, elo_post, …).
        w_grid: Grid of w values to try (default W_GRID).
        d_grid: Grid of d values to try (default D_GRID).
        initial_elo: Default Elo rating for teams without history.

    Returns:
        EnsembleResult with best (w, d), log-losses and full grid results.
    """
    # Log-loss de DC puro (w=0) — baseline v1
    dc_log_loss = _log_loss_from_preds(predictions_dc)

    grid_rows: list[dict] = []
    best_ll: float = float("inf")
    best_w: float = 0.0
    best_d: float = d_grid[0] if d_grid else 0.3

    for d in d_grid:
        elo_params = EloModelParams(draw_param=d)
        for w in w_grid:
            if w == 0.0:
                # w=0 → idéntico a DC (no-regresión); log-loss ya calculado
                ll = dc_log_loss
            else:
                # Calcular predicciones ensemble con Elo as-of (leak-free, R7)
                ensemble_preds: list[WindowPrediction] = []
                for pred in predictions_dc:
                    p_elo = predict_elo_backtest(
                        pred.home_code,
                        pred.away_code,
                        as_of_date=pred.date,  # anti-fuga: elo < fecha_partido
                        history=elo_history,
                        neutral=False,  # conservador: no tenemos info de neutral aquí
                        params=elo_params,
                        initial=initial_elo,
                        use_external=False,  # NUNCA externo en backtest (R7)
                    )
                    p_ens = ensemble(
                        (pred.prob_home, pred.prob_draw, pred.prob_away),
                        p_elo,
                        w,
                    )
                    ensemble_preds.append(WindowPrediction(
                        date=pred.date,
                        home_code=pred.home_code,
                        away_code=pred.away_code,
                        prob_home=p_ens.prob_home,
                        prob_draw=p_ens.prob_draw,
                        prob_away=p_ens.prob_away,
                        actual=pred.actual,
                        marginal_home=pred.marginal_home,
                        marginal_draw=pred.marginal_draw,
                        marginal_away=pred.marginal_away,
                    ))
                ll = _log_loss_from_preds(ensemble_preds)

            grid_rows.append({"w": w, "d": d, "log_loss": ll})
            if ll < best_ll:
                best_ll = ll
                best_w = w
                best_d = d

    grid_df = pd.DataFrame(grid_rows, columns=["w", "d", "log_loss"])

    return EnsembleResult(
        best_w=best_w,
        best_d=best_d,
        best_log_loss=best_ll,
        dc_log_loss=dc_log_loss,
        grid_results=grid_df,
    )
