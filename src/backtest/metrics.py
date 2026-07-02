"""src/backtest/metrics.py — Metricas 1X2 puras para el backtest walk-forward (R4–R6).

Todas las funciones son puras (sin estado, sin I/O). Usan los vectores de
predicciones y resultados reales de las ventanas walk-forward.

- log-loss: ``sklearn.metrics.log_loss`` con ``labels`` fijos ``["1","X","2"]``.
- Brier multiclase: suma de cuadrados contra one-hot (formula del design.md).
- Exactitud: argmax con desempate determinista por orden de ``OUTCOME_ORDER``.
- Calibracion: ``sklearn.calibration.calibration_curve`` con degradacion si hay
  pocos datos por clase (R5).
- Baselines: uniforme (1/3) y marginal por ventana (R6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.metrics import log_loss

from .walkforward import WindowPrediction, WindowResult

# Orden canónico de resultados (inmutable, R4).
# OUTCOME_ORDER fija el orden de las columnas de probs en todo el sistema.
OUTCOME_ORDER: tuple[str, str, str] = ("1", "X", "2")
OUTCOME_INDEX: dict[str, int] = {o: i for i, o in enumerate(OUTCOME_ORDER)}

# Orden lexicográfico que sklearn.metrics.log_loss asume internamente.
# log_loss espera que las columnas de y_prob estén en el mismo orden que
# sorted(labels). Para nuestros labels {"1","X","2"}: sorted = ["1","2","X"].
# Guardamos el mapeo de OUTCOME_ORDER → columna en el array reordenado para sklearn.
_SKLEARN_LABEL_ORDER: tuple[str, ...] = tuple(sorted(OUTCOME_ORDER))
# Índice de cada outcome en el orden que sklearn espera:
# _SKL_COL_MAP[k] = índice en _SKLEARN_LABEL_ORDER del k-ésimo outcome de OUTCOME_ORDER
_SKL_COL_MAP: tuple[int, ...] = tuple(
    _SKLEARN_LABEL_ORDER.index(o) for o in OUTCOME_ORDER
)


@dataclass
class MetricsResult:
    """Resultado de evaluar metricas sobre un conjunto de predicciones (R4).

    Attributes:
        log_loss: Multiclass log-loss (sklearn, lower is better).
        brier: Multiclass Brier score (own implementation, lower is better).
        accuracy: Fraction of correct predictions (argmax, deterministic tie-break).
        n_matches: Number of evaluated matches.
        n_skipped: Number of skipped matches.
    """

    log_loss: float
    brier: float
    accuracy: float
    n_matches: int
    n_skipped: int


@dataclass
class CalibrationData:
    """Datos de curva de calibracion por desenlace (R5).

    Attributes:
        outcome: Outcome label (``"1"``, ``"X"`` or ``"2"``).
        fraction_of_positives: Observed fractions from calibration_curve.
        mean_predicted_value: Mean predicted probabilities from calibration_curve.
        computable: False if too few samples for even 2 bins.
    """

    outcome: str
    fraction_of_positives: list[float]
    mean_predicted_value: list[float]
    computable: bool


def _build_arrays(
    predictions: list[WindowPrediction],
) -> tuple[list[str], np.ndarray]:
    """Construye los arrays de resultados reales y probabilidades (R4).

    Args:
        predictions: List of window predictions.

    Returns:
        Tuple of (y_true list of outcome strings, probs array n x 3 in OUTCOME_ORDER).
    """
    y_true = [p.actual for p in predictions]
    probs = np.array(
        [[p.prob_home, p.prob_draw, p.prob_away] for p in predictions], dtype=float
    )
    return y_true, probs


def compute_metrics(
    predictions: list[WindowPrediction],
    n_skipped: int,
    probs_override: np.ndarray | None = None,
) -> MetricsResult:
    """Calcula log-loss, Brier y exactitud sobre el conjunto de predicciones (R4).

    El calculo de Brier multiclase usa la formula del design.md::

        BS = (1/n) * sum_i sum_k (p_ik - o_ik)^2

    donde ``o_ik`` es el one-hot del desenlace real (rango 0-2, 0 = perfecto).

    La exactitud usa ``argmax`` con desempate determinista por orden de
    ``OUTCOME_ORDER`` (numpy ``argmax`` toma el primer maximo).

    Args:
        predictions: List of window predictions.
        n_skipped: Total number of skipped matches (included in the result).
        probs_override: If provided, use these probabilities instead of those in
            predictions (used for baselines).

    Returns:
        MetricsResult with all metrics.

    Raises:
        ValueError: If predictions is empty.
    """
    if not predictions:
        raise ValueError("No hay predicciones para evaluar")

    y_true, probs = _build_arrays(predictions)
    if probs_override is not None:
        probs = probs_override

    # Log-loss (sklearn, R4).
    # sklearn.metrics.log_loss espera columnas en orden lexicográfico (sorted).
    # Para labels {"1","X","2"}: sorted = ["1","2","X"].
    # Reordenamos las columnas de probs al orden léxico que sklearn asume.
    probs_skl = probs[:, list(_SKL_COL_MAP)]
    ll = float(log_loss(y_true, probs_skl, labels=list(_SKLEARN_LABEL_ORDER)))

    # Brier multiclase (formula del design.md, R4)
    n = len(y_true)
    one_hot = np.zeros((n, 3), dtype=float)
    for i, outcome in enumerate(y_true):
        one_hot[i, OUTCOME_INDEX[outcome]] = 1.0
    brier = float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))

    # Exactitud: argmax con desempate determinista (primer maximo, R4)
    predicted_indices = np.argmax(probs, axis=1)
    predicted_outcomes = [OUTCOME_ORDER[idx] for idx in predicted_indices]
    accuracy = float(np.mean([p == a for p, a in zip(predicted_outcomes, y_true)]))

    return MetricsResult(
        log_loss=ll,
        brier=brier,
        accuracy=accuracy,
        n_matches=n,
        n_skipped=n_skipped,
    )


def compute_calibration(
    predictions: list[WindowPrediction],
    bins: int = 10,
    probs_override: np.ndarray | None = None,
) -> list[CalibrationData]:
    """Calcula curvas de calibracion por desenlace (R5).

    Usa ``sklearn.calibration.calibration_curve`` con estrategia ``quantile``.
    SI un desenlace tiene menos muestras que ``bins``, reduce bins a
    ``max(2, n_muestras_clase)`` o marca como no computable (R5).

    Args:
        predictions: List of window predictions.
        bins: Number of calibration bins (default 10).
        probs_override: If provided, use these probabilities instead of those
            in predictions.

    Returns:
        List of CalibrationData, one per outcome in OUTCOME_ORDER.
    """
    if not predictions:
        return [
            CalibrationData(
                outcome=o,
                fraction_of_positives=[],
                mean_predicted_value=[],
                computable=False,
            )
            for o in OUTCOME_ORDER
        ]

    y_true, probs = _build_arrays(predictions)
    if probs_override is not None:
        probs = probs_override

    result = []
    for k, outcome in enumerate(OUTCOME_ORDER):
        y_bin = np.array([1 if y == outcome else 0 for y in y_true], dtype=int)
        n_pos = int(y_bin.sum())
        n_total = len(y_bin)

        # Degradacion: si hay menos muestras positivas que bins, reducir (R5).
        # Si n_pos == 0, la curva no es computable (ningún positivo real).
        effective_bins = bins
        if n_pos < bins:
            effective_bins = max(2, n_pos)

        if effective_bins < 2 or n_total < 2 or n_pos == 0:
            result.append(
                CalibrationData(
                    outcome=outcome,
                    fraction_of_positives=[],
                    mean_predicted_value=[],
                    computable=False,
                )
            )
            continue

        try:
            frac_pos, mean_pred = calibration_curve(
                y_bin, probs[:, k], n_bins=effective_bins, strategy="quantile"
            )
            result.append(
                CalibrationData(
                    outcome=outcome,
                    fraction_of_positives=frac_pos.tolist(),
                    mean_predicted_value=mean_pred.tolist(),
                    computable=True,
                )
            )
        except ValueError:
            result.append(
                CalibrationData(
                    outcome=outcome,
                    fraction_of_positives=[],
                    mean_predicted_value=[],
                    computable=False,
                )
            )

    return result


def make_uniform_probs(n: int) -> np.ndarray:
    """Devuelve la matriz de probabilidades uniformes (1/3 cada desenlace) (R6).

    Args:
        n: Number of matches.

    Returns:
        Array of shape (n, 3) filled with 1/3.
    """
    return np.full((n, 3), 1.0 / 3.0)


def make_marginal_probs(predictions: list[WindowPrediction]) -> np.ndarray:
    """Construye la matriz de probabilidades marginales por ventana (R6).

    Cada prediccion lleva sus marginales del entrenamiento de su ventana (precalculados
    en walkforward.run). Esta funcion las empaqueta en la matriz n x 3.

    Args:
        predictions: List of window predictions with marginal probabilities.

    Returns:
        Array of shape (n, 3) with marginal probabilities.
    """
    return np.array(
        [[p.marginal_home, p.marginal_draw, p.marginal_away] for p in predictions],
        dtype=float,
    )


def collect_all_predictions(
    window_results: list[WindowResult],
) -> tuple[list[WindowPrediction], int]:
    """Agrega todas las predicciones y el total de skipped de todos las ventanas (R4).

    Args:
        window_results: List of WindowResult objects.

    Returns:
        Tuple of (all predictions flattened, total n_skipped).
    """
    all_preds: list[WindowPrediction] = []
    total_skipped = 0
    for wr in window_results:
        all_preds.extend(wr.predictions)
        total_skipped += len(wr.skipped)
    return all_preds, total_skipped


def evaluate_all(
    window_results: list[WindowResult], bins: int = 10
) -> dict[str, Any]:
    """Evalua metricas agregadas + baselines + calibracion (R4–R6).

    Args:
        window_results: List of WindowResult objects from walkforward.run.
        bins: Number of calibration bins.

    Returns:
        Dict with keys ``"model"``, ``"uniform"``, ``"marginal"`` (MetricsResult)
        and ``"calibration"`` (list of CalibrationData).

    Raises:
        ValueError: If there are no predictions to evaluate.
    """
    all_preds, total_skipped = collect_all_predictions(window_results)
    if not all_preds:
        raise ValueError(
            "No hay predicciones para evaluar; todos los partidos fueron skipped "
            "o no hubo partidos en el rango indicado"
        )

    n = len(all_preds)
    model_metrics = compute_metrics(all_preds, total_skipped)
    uniform_probs = make_uniform_probs(n)
    marginal_probs = make_marginal_probs(all_preds)

    uniform_metrics = compute_metrics(all_preds, total_skipped, probs_override=uniform_probs)
    marginal_metrics = compute_metrics(all_preds, total_skipped, probs_override=marginal_probs)
    calib = compute_calibration(all_preds, bins=bins)

    return {
        "model": model_metrics,
        "uniform": uniform_metrics,
        "marginal": marginal_metrics,
        "calibration": calib,
    }
