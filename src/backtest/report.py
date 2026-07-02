"""src/backtest/report.py — Ensamblado y escritura determinista del reporte (R7, R9, R13).

Orquesta el backtest walk-forward, las metricas, el ROI opcional y el grid opcional
de hiperparametros, y escribe los resultados en disco:
- ``summary.json``: configuracion, metricas agregadas, baselines, low_data, ROI, ranking.
- ``windows.csv``: metricas por ventana.
- ``calibration.csv``: curvas de calibracion por desenlace y bin.

Todos los resultados son deterministas (sin reloj, sin RNG). El JSON usa
``sort_keys=True``, floats redondeados a 6 decimales. La escritura ocurre SOLO
dentro de ``out_dir`` (R9).
"""

from __future__ import annotations

import csv
import json
import warnings
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from ..ingestion.teams import all_teams
from .metrics import (
    CalibrationData,
    MetricsResult,
    collect_all_predictions,
    compute_calibration,
    compute_metrics,
    evaluate_all,
    make_marginal_probs,
    make_uniform_probs,
)
from .roi import ROIResult, evaluate_roi
from .walkforward import BacktestConfig, WindowResult, run

# Codigos FIFA de las 48 selecciones del torneo (R13)
_TORNEO_48: frozenset[str] = frozenset(t.code for t in all_teams())


def _round_floats(obj: Any, decimals: int = 6) -> Any:
    """Redondea recursivamente todos los float a ``decimals`` decimales (R9).

    Args:
        obj: Any Python object (dict, list, float, etc.).
        decimals: Number of decimal places.

    Returns:
        Object with all floats rounded.
    """
    if isinstance(obj, float):
        return round(obj, decimals)
    if isinstance(obj, dict):
        return {k: _round_floats(v, decimals) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, decimals) for v in obj]
    return obj


def _metrics_to_dict(m: MetricsResult) -> dict[str, Any]:
    """Serializa MetricsResult a dict con claves ordenadas (R9).

    Args:
        m: MetricsResult to serialize.

    Returns:
        Plain dict with log_loss, brier, accuracy, n_matches, n_skipped.
    """
    return {
        "accuracy": m.accuracy,
        "brier": m.brier,
        "log_loss": m.log_loss,
        "n_matches": m.n_matches,
        "n_skipped": m.n_skipped,
    }


def _calib_to_rows(
    calib_data: list[CalibrationData], window_start: str, window_end: str
) -> list[dict[str, Any]]:
    """Convierte datos de calibracion en filas para calibration.csv (R9).

    Args:
        calib_data: List of CalibrationData objects.
        window_start: Window start date string.
        window_end: Window end date string.

    Returns:
        List of row dicts for csv.DictWriter.
    """
    rows = []
    for cd in calib_data:
        if not cd.computable:
            rows.append(
                {
                    "window_start": window_start,
                    "window_end": window_end,
                    "outcome": cd.outcome,
                    "bin": "",
                    "fraction_of_positives": "",
                    "mean_predicted_value": "",
                    "computable": "False",
                }
            )
        else:
            for bin_idx, (frac, mean_pred) in enumerate(
                zip(cd.fraction_of_positives, cd.mean_predicted_value)
            ):
                rows.append(
                    {
                        "window_start": window_start,
                        "window_end": window_end,
                        "outcome": cd.outcome,
                        "bin": bin_idx,
                        "fraction_of_positives": round(frac, 6),
                        "mean_predicted_value": round(mean_pred, 6),
                        "computable": "True",
                    }
                )
    return rows


def _build_low_data_section(
    params_low_data_teams: list[str],
    attack: dict[str, float],
    defense: dict[str, float],
) -> dict[str, Any]:
    """Construye la seccion low_data para summary.json (R13).

    Incluye attack/defense de cada equipo low-data y un flag booleano si alguno
    de los 48 esta en la lista.

    Args:
        params_low_data_teams: List of team codes with low data.
        attack: Dict of attack parameters.
        defense: Dict of defense parameters.

    Returns:
        Dict with ``teams`` list and ``low_data_en_torneo`` bool.
    """
    teams_info = []
    for code in sorted(params_low_data_teams):
        teams_info.append(
            {
                "code": code,
                "attack": attack.get(code),
                "defense": defense.get(code),
            }
        )
    low_data_en_torneo = bool(
        set(params_low_data_teams) & _TORNEO_48
    )
    return {
        "low_data_en_torneo": low_data_en_torneo,
        "teams": teams_info,
    }


def run_backtest(
    cfg: BacktestConfig,
    form_factory: Callable[[str], Callable[[str, str], tuple[float, float]]] | None = None,
) -> dict[str, Any]:
    """Ejecuta el backtest walk-forward y devuelve el resumen como dict (R7, R9, R13).

    Args:
        cfg: Backtest configuration.
        form_factory: Optional callable ``(as_of) → form_factor_fn`` (Feature 16, R5).
            ``None`` → v1 behaviour exact.

    Returns:
        Summary dict ready for JSON serialization and writing to disk.

    Raises:
        SilverNotFoundError: If the silver CSV is missing.
        ValueError: If no evaluation windows can be generated.
    """
    from ..models.dixon_coles import DCConfig, fit_dixon_coles

    window_results, effective_to = run(cfg, form_factory=form_factory)
    all_preds, total_skipped = collect_all_predictions(window_results)

    if not all_preds:
        raise ValueError(
            "No hay predicciones para reportar; todos los partidos fueron omitidos "
            "o el rango no contiene partidos evaluables"
        )

    # Metricas agregadas (R4-R6)
    eval_result = evaluate_all(window_results, bins=cfg.bins)
    model_metrics: MetricsResult = eval_result["model"]
    uniform_metrics: MetricsResult = eval_result["uniform"]
    marginal_metrics: MetricsResult = eval_result["marginal"]
    calib_all: list[CalibrationData] = eval_result["calibration"]

    # ROI opcional (R8)
    roi_result: ROIResult | None = None
    if cfg.odds_csv is not None:
        roi_result = evaluate_roi(all_preds, cfg.odds_csv, cfg.value_threshold)

    # Low-data del refit FINAL para R13
    dc_config = DCConfig(xi=cfg.xi, reg_lambda=cfg.reg_lambda, min_matches=cfg.min_matches)
    final_params = fit_dixon_coles(
        effective_to,
        silver_path=cfg.silver_path,
        config=dc_config,
    )
    low_data_section = _build_low_data_section(
        final_params.low_data_teams,
        final_params.attack,
        final_params.defense,
    )

    # Advertencia si low_data interseca las 48 del torneo (R13)
    if low_data_section["low_data_en_torneo"]:
        torneo_in_low = sorted(
            set(final_params.low_data_teams) & _TORNEO_48
        )
        warnings.warn(
            f"⚠️ low_data incluye selecciones del torneo: {torneo_in_low} "
            "(fuerzas pueden estar sobreajustadas por pocos datos — "
            "caso 'isle_of_man': se visibilizan, no se recortan; design.md R13)",
            UserWarning,
            stacklevel=2,
        )

    # Metricas por ventana para windows.csv
    window_rows = []
    calib_rows = []
    for wr in window_results:
        if not wr.predictions:
            # Ventana sin predicciones: solo registrar conteos
            window_rows.append(
                {
                    "window_start": wr.window_start,
                    "window_end": wr.window_end,
                    "n_matches": 0,
                    "n_skipped": len(wr.skipped),
                    "log_loss_model": "",
                    "brier_model": "",
                    "accuracy_model": "",
                    "log_loss_uniform": "",
                    "brier_uniform": "",
                    "accuracy_uniform": "",
                    "log_loss_marginal": "",
                    "brier_marginal": "",
                    "accuracy_marginal": "",
                }
            )
            continue
        n_skip_w = len(wr.skipped)
        try:
            m_model = compute_metrics(wr.predictions, n_skip_w)
            n_w = len(wr.predictions)
            uni_probs = make_uniform_probs(n_w)
            marg_probs = make_marginal_probs(wr.predictions)
            m_uniform = compute_metrics(wr.predictions, n_skip_w, probs_override=uni_probs)
            m_marginal = compute_metrics(wr.predictions, n_skip_w, probs_override=marg_probs)
            calib_w = compute_calibration(wr.predictions, bins=cfg.bins)
        except ValueError:
            continue

        window_rows.append(
            {
                "window_start": wr.window_start,
                "window_end": wr.window_end,
                "n_matches": m_model.n_matches,
                "n_skipped": m_model.n_skipped,
                "log_loss_model": round(m_model.log_loss, 6),
                "brier_model": round(m_model.brier, 6),
                "accuracy_model": round(m_model.accuracy, 6),
                "log_loss_uniform": round(m_uniform.log_loss, 6),
                "brier_uniform": round(m_uniform.brier, 6),
                "accuracy_uniform": round(m_uniform.accuracy, 6),
                "log_loss_marginal": round(m_marginal.log_loss, 6),
                "brier_marginal": round(m_marginal.brier, 6),
                "accuracy_marginal": round(m_marginal.accuracy, 6),
            }
        )
        calib_rows.extend(_calib_to_rows(calib_w, wr.window_start, wr.window_end))

    # Construir summary.json (R9, R13)
    summary: dict[str, Any] = {
        "as_of": effective_to,
        "config": {
            "bins": cfg.bins,
            "from_date": cfg.from_date,
            "min_matches": cfg.min_matches,
            "odds_csv": str(cfg.odds_csv) if cfg.odds_csv else None,
            "out_dir": str(cfg.out_dir),
            "refit_every": cfg.refit_every,
            "reg_lambda": cfg.reg_lambda,
            "silver_path": str(cfg.silver_path),
            "to_date": cfg.to_date,
            "value_threshold": cfg.value_threshold,
            "xi": cfg.xi,
        },
        "low_data": low_data_section,
        "metrics": {
            "marginal": _metrics_to_dict(marginal_metrics),
            "model": _metrics_to_dict(model_metrics),
            "uniform": _metrics_to_dict(uniform_metrics),
        },
        "n_windows": len(window_results),
    }

    if roi_result is not None:
        summary["roi"] = {
            "n_bets": roi_result.n_bets,
            "n_descartes_cuotas": roi_result.n_descartes_cuotas,
            "n_sin_match": roi_result.n_sin_match,
            "n_wins": roi_result.n_wins,
            "retorno": round(roi_result.retorno, 6),
            "roi": round(roi_result.roi, 6),
            "stake": round(roi_result.stake, 6),
        }

    return summary, window_rows, calib_rows


def run_grid(
    cfg: BacktestConfig,
    xis: list[float] | None = None,
    reg_lambdas: list[float] | None = None,
    importance_scales: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Ejecuta el grid de hiperparametros walk-forward y devuelve el ranking (R7, R4 feature 12).

    Usa el MISMO protocolo walk-forward por cada combinacion (xi, reg_lambda,
    [escala_importancia]).  La dimension de importancia es OPCIONAL: cuando
    ``importance_scales`` es ``None`` o una lista unitaria ``[1.0]`` el grid es
    bidimensional y reproduce exactamente el comportamiento previo (no-regresion).

    Una escala de importancia ``s`` multiplica globalmente todos los factores del
    mapa v2: ``importance_map[t] = s * base_factor[t]``.  Escala 1.0 = factores
    base sin modificar.

    Args:
        cfg: Base backtest configuration.
        xis: List of xi values to evaluate. Default: [0.5, 0.65, 0.8].
        reg_lambdas: List of reg_lambda values to evaluate. Default: [0.5, 1.0, 2.0].
        importance_scales: List of global importance scale factors to evaluate.
            ``None`` → no importance weighting (v1 behaviour). Each scale != 1.0
            requires the silver to have a ``tournament`` column.

    Returns:
        List of ranking dicts sorted by (log_loss, brier).
    """
    if xis is None:
        xis = [0.5, 0.65, 0.8]
    if reg_lambdas is None:
        reg_lambdas = [0.5, 1.0, 2.0]

    # Determinar las configuraciones de importancia para el grid.
    # None → sin importancia (v1). Una lista de escalas → v2 grid.
    importance_configs: list[float | None]
    if importance_scales is None:
        importance_configs = [None]
    else:
        importance_configs = list(importance_scales)  # type: ignore[assignment]

    ranking: list[dict[str, Any]] = []

    for xi in xis:
        for reg_lambda in reg_lambdas:
            for imp_scale in importance_configs:
                grid_cfg = BacktestConfig(
                    from_date=cfg.from_date,
                    to_date=cfg.to_date,
                    refit_every=cfg.refit_every,
                    xi=xi,
                    reg_lambda=reg_lambda,
                    min_matches=cfg.min_matches,
                    bins=cfg.bins,
                    value_threshold=cfg.value_threshold,
                    out_dir=cfg.out_dir,
                    odds_csv=cfg.odds_csv,
                    silver_path=cfg.silver_path,
                )

                # Construir el mapa de importancia escalado si se requiere (R4 f12)
                imp_map: dict[str, float] | None = None
                if imp_scale is not None:
                    from ..models.importance import TIER_FACTORS, build_importance_map

                    try:
                        _df = pd.read_csv(cfg.silver_path, usecols=["tournament"])
                        scaled = {t: v * float(imp_scale) for t, v in TIER_FACTORS.items()}
                        imp_map = build_importance_map(
                            list(_df["tournament"].astype(str).unique()),
                            tier_factors=scaled,
                        )
                    except Exception:  # noqa: BLE001
                        imp_map = None  # graceful fallback

                try:
                    window_results, _ = run(grid_cfg, importance_map=imp_map)
                    all_preds, total_skipped = collect_all_predictions(window_results)
                    if not all_preds:
                        continue
                    m = compute_metrics(all_preds, total_skipped)
                    entry: dict[str, Any] = {
                        "xi": xi,
                        "reg_lambda": reg_lambda,
                        "log_loss": round(m.log_loss, 6),
                        "brier": round(m.brier, 6),
                        "accuracy": round(m.accuracy, 6),
                        "n_matches": m.n_matches,
                    }
                    if imp_scale is not None:
                        entry["importance_scale"] = imp_scale
                    ranking.append(entry)
                except (ValueError, Exception) as exc:  # noqa: BLE001
                    warnings.warn(
                        f"Grid xi={xi}, reg_lambda={reg_lambda}, "
                        f"imp_scale={imp_scale} falló: {exc}",
                        UserWarning,
                        stacklevel=2,
                    )

    # Ordenar por (log_loss, brier) ascendente (R7)
    ranking.sort(key=lambda r: (r["log_loss"], r["brier"]))
    return ranking


def write_report(
    cfg: BacktestConfig,
    run_grid_flag: bool = False,
    xis: list[float] | None = None,
    reg_lambdas: list[float] | None = None,
    importance_scales: list[float] | None = None,
    form_factory: Callable[[str], Callable[[str, str], tuple[float, float]]] | None = None,
) -> dict[str, Any]:
    """Orquesta el backtest completo y escribe los archivos en ``out_dir`` (R9, R13, R4 feature 12).

    Escribe SOLO dentro de ``out_dir``. El JSON usa ``sort_keys=True``,
    ``ensure_ascii=False``, ``indent=2``; floats redondeados a 6 decimales.

    Args:
        cfg: Backtest configuration.
        run_grid_flag: If True, run hyperparameter grid search (R7).
        xis: Grid xi values (only used if run_grid_flag=True).
        reg_lambdas: Grid reg_lambda values (only used if run_grid_flag=True).
        importance_scales: Grid importance scale values (R4 feature 12).
            ``None`` → no importance dimension in the grid.

    Returns:
        The summary dict written to disk.

    Raises:
        SilverNotFoundError: If silver CSV is missing.
        ValueError: If no predictions can be made.
    """
    summary, window_rows, calib_rows = run_backtest(cfg, form_factory=form_factory)

    # Grid opcional (R7, R4 feature 12) — SOLO bajo flag
    if run_grid_flag:
        grid_ranking = run_grid(
            cfg, xis=xis, reg_lambdas=reg_lambdas, importance_scales=importance_scales
        )
        summary["grid_ranking"] = grid_ranking

    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # summary.json (R9)
    summary_rounded = _round_floats(summary)
    (out_dir / "summary.json").write_text(
        json.dumps(summary_rounded, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # windows.csv (R9)
    windows_fieldnames = [
        "window_start", "window_end", "n_matches", "n_skipped",
        "log_loss_model", "brier_model", "accuracy_model",
        "log_loss_uniform", "brier_uniform", "accuracy_uniform",
        "log_loss_marginal", "brier_marginal", "accuracy_marginal",
    ]
    with (out_dir / "windows.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=windows_fieldnames)
        writer.writeheader()
        writer.writerows(window_rows)

    # calibration.csv (R9)
    calib_fieldnames = [
        "window_start", "window_end", "outcome", "bin",
        "fraction_of_positives", "mean_predicted_value", "computable",
    ]
    with (out_dir / "calibration.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=calib_fieldnames)
        writer.writeheader()
        writer.writerows(calib_rows)

    return summary
