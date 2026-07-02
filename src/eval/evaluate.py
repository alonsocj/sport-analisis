"""src/eval/evaluate.py — Evaluación predicho-vs-ocurrido para el Mundial 2026 (R6–R11).

Cruza el log de predicciones con los resultados reales del silver, calcula métricas
1X2 (reutilizando ``src/backtest/metrics.py``), calibración, Brier de mercado
(O/U 2.5 y BTTS), error de goles esperados (lambda vs goles reales) y escribe el
reporte determinista bajo ``data/reports/evaluacion/``.

Contratos:
- Join por ``match_id``; sin marcador real → ``skipped`` (R6).
- Métricas 1X2 via ``compute_metrics`` / ``compute_calibration`` de backtest (R7, R8).
- Brier binario de mercados solo con ``--markets`` (R9).
- RMSE/MAE de lambdas vs goles reales (R10).
- Reporte determinista byte a byte bajo ``data/reports/evaluacion/`` (R11).
- Escritura confinada a ``data/``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..backtest.metrics import (
    OUTCOME_ORDER,
    CalibrationData,
    MetricsResult,
    WindowPrediction,
    compute_calibration,
    compute_metrics,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_LOG_PATH = Path("data/predictions/log.csv")
DEFAULT_SILVER_PATH = Path("data/silver/matches.csv")
DEFAULT_REPORT_DIR = Path("data/reports/evaluacion")

# Columnas del silver que se necesitan para el join (R6).
SILVER_REQUIRED = ("match_id", "date", "home_code", "away_code", "home_goals", "away_goals")


# ---------------------------------------------------------------------------
# Helpers de seguridad de escritura
# ---------------------------------------------------------------------------


def _assert_under_data(path: Path) -> None:
    """Verifica que la ruta tenga 'data' como componente del path (R11).

    La escritura de reportes debe ocurrir bajo un directorio ``data/`` en el
    árbol de rutas. Se verifica que alguna parte del path contenga el
    segmento ``data`` (case-sensitive).

    Args:
        path: Path to validate.

    Raises:
        ValueError: If 'data' is not a component of the path.
    """
    parts = Path(path).resolve().parts
    if "data" not in parts:
        raise ValueError(
            f"Escritura confinada a data/; ruta rechazada: {path}"
        )


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------


def load_log(log_path: Path | str = DEFAULT_LOG_PATH) -> pd.DataFrame:
    """Carga el log de predicciones.

    Args:
        log_path: Path to the predictions log CSV.

    Returns:
        DataFrame with log columns.

    Raises:
        FileNotFoundError: If the log file does not exist.
    """
    path = Path(log_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"No existe el log de predicciones en {path}; "
            "ejecuta `predict-log` primero"
        )
    return pd.read_csv(path, dtype=str)


def load_silver(silver_path: Path | str = DEFAULT_SILVER_PATH) -> pd.DataFrame:
    """Carga el silver con resultados reales.

    Args:
        silver_path: Path to the silver matches CSV.

    Returns:
        DataFrame with silver columns.

    Raises:
        FileNotFoundError: If the silver file does not exist.
        ValueError: If required columns are missing.
    """
    path = Path(silver_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"No existe el silver en {path}; "
            "ejecuta `build-features` primero"
        )
    df = pd.read_csv(path, dtype=str)
    missing = [c for c in SILVER_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            f"Silver falta columnas requeridas: {', '.join(missing)}"
        )
    return df


# ---------------------------------------------------------------------------
# Join predicho-vs-ocurrido (R6)
# ---------------------------------------------------------------------------


def _normalize_code(code: str) -> str:
    """Normaliza un código/nombre de equipo para el join de fallback."""
    return code.strip().upper()


def join_log_silver(
    log: pd.DataFrame,
    silver: pd.DataFrame,
    from_date: str | None = None,
    to_date: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cruza el log con los resultados reales del silver (R6).

    Join primario por ``match_id``. Los fixtures del log sin marcador real en
    silver (o con marcador no numérico) se cuentan como ``skipped``.

    Filtros opcionales por fecha sobre ``match_date`` del log.

    Args:
        log: Predictions log DataFrame.
        silver: Silver matches DataFrame with results.
        from_date: Optional inclusive lower bound on match_date (YYYY-MM-DD).
        to_date: Optional inclusive upper bound on match_date (YYYY-MM-DD).

    Returns:
        Tuple of (evaluable DataFrame, skipped DataFrame).
        Evaluable has columns from log + home_goals, away_goals (numeric).
        Skipped has log columns + 'skip_reason'.
    """
    log = log.copy()

    # Filtros de fecha
    if from_date:
        log = log[log["match_date"] >= from_date]
    if to_date:
        log = log[log["match_date"] <= to_date]

    if log.empty:
        skipped = log.copy()
        skipped["skip_reason"] = "sin_rango"
        return pd.DataFrame(), skipped

    # Construir lookup de silver por match_id
    silver_by_id: dict[str, dict] = {}
    for _, srow in silver.iterrows():
        mid = str(srow.get("match_id", "")).strip()
        if mid:
            silver_by_id[mid] = srow.to_dict()

    evaluable_rows = []
    skipped_rows = []

    for _, lrow in log.iterrows():
        mid = str(lrow.get("match_id", "")).strip()
        srow = silver_by_id.get(mid)

        if srow is None:
            skip = lrow.to_dict()
            skip["skip_reason"] = "sin_resultado_real"
            skipped_rows.append(skip)
            continue

        # Verificar que hay marcador numérico
        hg_raw = srow.get("home_goals", "")
        ag_raw = srow.get("away_goals", "")
        try:
            hg = float(hg_raw)
            ag = float(ag_raw)
        except (TypeError, ValueError):
            skip = lrow.to_dict()
            skip["skip_reason"] = "marcador_no_disponible"
            skipped_rows.append(skip)
            continue

        row = lrow.to_dict()
        row["home_goals"] = hg
        row["away_goals"] = ag
        evaluable_rows.append(row)

    evaluable = pd.DataFrame(evaluable_rows) if evaluable_rows else pd.DataFrame()
    skipped = pd.DataFrame(skipped_rows) if skipped_rows else pd.DataFrame()
    return evaluable, skipped


# ---------------------------------------------------------------------------
# Conversión a WindowPrediction para reusar backtest.metrics (R7, R8)
# ---------------------------------------------------------------------------


def _outcome_from_goals(home_goals: float, away_goals: float) -> str:
    """Determina el desenlace real ('1', 'X', '2') desde los goles.

    Args:
        home_goals: Goals scored by the home team.
        away_goals: Goals scored by the away team.

    Returns:
        '1' for home win, 'X' for draw, '2' for away win.
    """
    if home_goals > away_goals:
        return "1"
    if home_goals == away_goals:
        return "X"
    return "2"


def _to_float_safe(val: Any) -> float:
    """Convierte a float de forma defensiva; ValueError si no es posible."""
    try:
        return float(val)
    except (TypeError, ValueError) as e:
        raise ValueError(f"No se puede convertir a float: {val!r}") from e


def evaluable_to_window_predictions(evaluable: pd.DataFrame) -> list[WindowPrediction]:
    """Convierte el DataFrame evaluable a lista de WindowPrediction para backtest.metrics (R7).

    Usa marginal_home/draw/away = 1/3 (uniforme, ya que no tenemos la marginal
    de la ventana de entrenamiento en este contexto; es solo necesaria para baselines
    que no se calculan en eval, sino en backtest).

    Args:
        evaluable: DataFrame with log columns + home_goals, away_goals.

    Returns:
        List of WindowPrediction objects for use with compute_metrics / compute_calibration.
    """
    preds = []
    for _, row in evaluable.iterrows():
        hg = float(row["home_goals"])
        ag = float(row["away_goals"])
        actual = _outcome_from_goals(hg, ag)
        preds.append(
            WindowPrediction(
                date=str(row.get("match_date", "")),
                home_code=str(row.get("home_code", "")),
                away_code=str(row.get("away_code", "")),
                prob_home=_to_float_safe(row["p_home"]),
                prob_draw=_to_float_safe(row["p_draw"]),
                prob_away=_to_float_safe(row["p_away"]),
                actual=actual,
                marginal_home=1.0 / 3.0,
                marginal_draw=1.0 / 3.0,
                marginal_away=1.0 / 3.0,
            )
        )
    return preds


# ---------------------------------------------------------------------------
# Métricas de mercado (R9)
# ---------------------------------------------------------------------------


def _brier_binary(p_pred: np.ndarray, o_real: np.ndarray) -> float:
    """Brier binario: mean((p - o)^2).

    Args:
        p_pred: Predicted probabilities array.
        o_real: Observed binary outcomes array (0 or 1).

    Returns:
        Brier score as float.
    """
    return float(np.mean((p_pred - o_real) ** 2))


def compute_market_metrics(evaluable: pd.DataFrame) -> dict[str, float] | None:
    """Calcula Brier binario de O/U 2.5 y BTTS sobre partidos evaluables con mercados (R9).

    Solo se calcula si ``p_over25`` y ``p_btts`` están presentes y no vacías.

    Args:
        evaluable: DataFrame with log columns + home_goals, away_goals.

    Returns:
        Dict with 'brier_over25' and 'brier_btts', or None if market columns absent.
    """
    if evaluable.empty:
        return None

    # Verificar que las columnas de mercado están presentes y no vacías
    has_over = "p_over25" in evaluable.columns
    has_btts = "p_btts" in evaluable.columns
    if not (has_over and has_btts):
        return None

    # Filtrar solo filas con valores de mercado válidos
    mask = (
        evaluable["p_over25"].astype(str).str.strip().ne("")
        & evaluable["p_btts"].astype(str).str.strip().ne("")
    )
    sub = evaluable[mask]
    if sub.empty:
        return None

    p_over25 = sub["p_over25"].astype(float).to_numpy()
    p_btts = sub["p_btts"].astype(float).to_numpy()
    hg = sub["home_goals"].astype(float).to_numpy()
    ag = sub["away_goals"].astype(float).to_numpy()

    # over real: total_goals > 2.5 (R9)
    over_real = ((hg + ag) > 2.5).astype(float)
    # btts real: hg >= 1 y ag >= 1 (R9)
    btts_real = ((hg >= 1) & (ag >= 1)).astype(float)

    return {
        "brier_over25": _brier_binary(p_over25, over_real),
        "brier_btts": _brier_binary(p_btts, btts_real),
        "n": int(len(sub)),
    }


# ---------------------------------------------------------------------------
# Error de goles esperados (R10)
# ---------------------------------------------------------------------------


def compute_lambda_error(evaluable: pd.DataFrame) -> dict[str, float]:
    """RMSE y MAE entre lambda_home/away y goles reales (R10).

    Apila (lambda_home, home_goals) y (lambda_away, away_goals) en un vector.

    Args:
        evaluable: DataFrame with log columns + home_goals, away_goals.

    Returns:
        Dict with 'rmse', 'mae', 'n'.
    """
    if evaluable.empty:
        return {"rmse": float("nan"), "mae": float("nan"), "n": 0}

    lh = evaluable["lambda_home"].astype(float).to_numpy()
    la = evaluable["lambda_away"].astype(float).to_numpy()
    hg = evaluable["home_goals"].astype(float).to_numpy()
    ag = evaluable["away_goals"].astype(float).to_numpy()

    pred_goals = np.concatenate([lh, la])
    real_goals = np.concatenate([hg, ag])

    errors = pred_goals - real_goals
    rmse = float(np.sqrt(np.mean(errors**2)))
    mae = float(np.mean(np.abs(errors)))

    return {"rmse": rmse, "mae": mae, "n": int(len(pred_goals))}


# ---------------------------------------------------------------------------
# Reporte determinista (R11)
# ---------------------------------------------------------------------------


def _calibration_to_summary(cal_data: list[CalibrationData]) -> list[dict]:
    """Serializa calibración a lista de dicts para summary.json.

    Args:
        cal_data: List of CalibrationData from compute_calibration.

    Returns:
        List of serializable dicts.
    """
    return [
        {
            "outcome": cd.outcome,
            "computable": cd.computable,
            "fraction_of_positives": cd.fraction_of_positives,
            "mean_predicted_value": cd.mean_predicted_value,
        }
        for cd in cal_data
    ]


def _metrics_to_dict(m: MetricsResult) -> dict:
    """Serializa MetricsResult a dict.

    Args:
        m: MetricsResult instance.

    Returns:
        Plain dict.
    """
    return {
        "log_loss": m.log_loss,
        "brier": m.brier,
        "accuracy": m.accuracy,
        "n_matches": m.n_matches,
        "n_skipped": m.n_skipped,
    }


def write_report(
    evaluable: pd.DataFrame,
    skipped: pd.DataFrame,
    metrics: MetricsResult,
    calibration: list[CalibrationData],
    lambda_error: dict[str, float],
    out_dir: Path | str = DEFAULT_REPORT_DIR,
    market_metrics: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Escribe el reporte determinista bajo data/reports/evaluacion/ (R11).

    Genera:
    - ``summary.json`` con ``sort_keys=True``.
    - ``per_match.csv`` (una fila por partido evaluable).
    - ``calibration.csv``.

    Args:
        evaluable: DataFrame of evaluable matches with all metrics columns.
        skipped: DataFrame of skipped matches.
        metrics: MetricsResult from compute_metrics.
        calibration: List of CalibrationData from compute_calibration.
        lambda_error: Dict with rmse, mae, n from compute_lambda_error.
        out_dir: Output directory (must be under data/).
        market_metrics: Optional market metrics dict (R9).

    Returns:
        Dict with report paths and summary data.

    Raises:
        ValueError: If out_dir is not under data/.
    """
    out_dir = Path(out_dir)
    _assert_under_data(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # summary.json (R11): sort_keys=True para determinismo byte a byte
    summary: dict[str, Any] = {
        "metrics_1x2": _metrics_to_dict(metrics),
        "n_evaluable": len(evaluable),
        "n_skipped": len(skipped),
        "lambda_error": lambda_error,
        "calibration_summary": _calibration_to_summary(calibration),
    }
    if market_metrics is not None:
        summary["market_metrics"] = market_metrics

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # per_match.csv: una fila por partido evaluable
    per_match_path = out_dir / "per_match.csv"
    if not evaluable.empty:
        # Añadir columna de desenlace real
        pm = evaluable.copy()
        pm["actual_outcome"] = pm.apply(
            lambda r: _outcome_from_goals(float(r["home_goals"]), float(r["away_goals"])),
            axis=1,
        )
        pm.to_csv(per_match_path, index=False)
    else:
        pd.DataFrame().to_csv(per_match_path, index=False)

    # calibration.csv
    cal_path = out_dir / "calibration.csv"
    cal_rows = []
    for cd in calibration:
        if cd.computable:
            for frac, mean_pred in zip(
                cd.fraction_of_positives, cd.mean_predicted_value
            ):
                cal_rows.append({
                    "outcome": cd.outcome,
                    "fraction_of_positives": frac,
                    "mean_predicted_value": mean_pred,
                })
    pd.DataFrame(cal_rows).to_csv(cal_path, index=False)

    return {
        "summary_path": str(summary_path),
        "per_match_path": str(per_match_path),
        "calibration_path": str(cal_path),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Función principal de evaluación (R6–R11)
# ---------------------------------------------------------------------------


def evaluate(
    log_path: Path | str = DEFAULT_LOG_PATH,
    silver_path: Path | str = DEFAULT_SILVER_PATH,
    out_dir: Path | str = DEFAULT_REPORT_DIR,
    from_date: str | None = None,
    to_date: str | None = None,
    include_markets: bool = False,
    bins: int = 10,
    model_version_filter: str | None = None,
) -> dict[str, Any]:
    """Evalúa predicciones contra resultados reales (R6–R11, R7 feature 12).

    Carga el log y el silver, hace el join, calcula métricas y escribe el reporte.

    Args:
        log_path: Path to the predictions log CSV.
        silver_path: Path to the silver matches CSV.
        out_dir: Output directory for reports (must be under data/).
        from_date: Optional inclusive lower bound on match_date (YYYY-MM-DD).
        to_date: Optional inclusive upper bound on match_date (YYYY-MM-DD).
        include_markets: If True, compute Brier for O/U 2.5 and BTTS (R9).
        bins: Number of calibration bins (R8).
        model_version_filter: If set, only evaluate rows with this model_version
            (R7 feature 12). E.g. ``"dc-v1"`` or ``"dc-v2"``. ``None`` → all versions.

    Returns:
        Dict with keys: 'n_evaluable', 'n_skipped', 'metrics', 'lambda_error',
        'report' (sub-dict with paths), and optionally 'market_metrics'.

    Raises:
        FileNotFoundError: If log or silver do not exist.
        ValueError: If there are evaluable matches but metrics cannot be computed.
    """
    log = load_log(log_path)
    silver = load_silver(silver_path)

    # Filtro por versión del modelo (R7 feature 12)
    if model_version_filter is not None and "model_version" in log.columns:
        log = log[log["model_version"] == model_version_filter].copy()

    evaluable, skipped = join_log_silver(log, silver, from_date=from_date, to_date=to_date)

    n_evaluable = len(evaluable)
    n_skipped = len(skipped)

    if n_evaluable == 0:
        # Sin evaluables: retornar estado claro (R13)
        return {
            "n_evaluable": 0,
            "n_skipped": n_skipped,
            "metrics": None,
            "lambda_error": None,
            "market_metrics": None,
            "all_skipped": True,
        }

    # Convertir a WindowPrediction para reusar backtest.metrics (R7)
    window_preds = evaluable_to_window_predictions(evaluable)

    # Métricas 1X2 (R7)
    metrics = compute_metrics(window_preds, n_skipped=n_skipped)

    # Calibración (R8)
    calibration = compute_calibration(window_preds, bins=bins)

    # Error de lambda (R10)
    lambda_error = compute_lambda_error(evaluable)

    # Mercados opcionales (R9)
    market_metrics = None
    if include_markets:
        market_metrics = compute_market_metrics(evaluable)

    # Reporte determinista (R11)
    report = write_report(
        evaluable=evaluable,
        skipped=skipped,
        metrics=metrics,
        calibration=calibration,
        lambda_error=lambda_error,
        out_dir=out_dir,
        market_metrics=market_metrics,
    )

    return {
        "n_evaluable": n_evaluable,
        "n_skipped": n_skipped,
        "metrics": _metrics_to_dict(metrics),
        "lambda_error": lambda_error,
        "market_metrics": market_metrics,
        "report": report,
        "all_skipped": False,
    }
