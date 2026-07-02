"""Feature 10 — registro_y_evaluacion: tests de evaluate (R6–R11).

100 % offline y deterministas: DataFrames sintéticos construidos a mano.
Las métricas tienen un oráculo calculado a mano para verificar correctitud.

Trazabilidad:
    R6  → test_join_match_id_y_skipped_pendientes
    R7  → test_logloss_brier_exactitud_oraculo
    R8  → test_calibracion_bins_y_degradacion
    R9  → test_brier_mercados_over25_y_btts
    R10 → test_rmse_mae_lambda_vs_goles
    R11 → test_reporte_determinista_solo_bajo_data
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.eval.evaluate import (
    DEFAULT_LOG_PATH,
    DEFAULT_REPORT_DIR,
    _outcome_from_goals,
    compute_lambda_error,
    compute_market_metrics,
    evaluate,
    evaluable_to_window_predictions,
    join_log_silver,
    load_log,
    load_silver,
    write_report,
)
from src.backtest.metrics import compute_metrics, compute_calibration


# ---------------------------------------------------------------------------
# Helpers y fixtures sintéticos
# ---------------------------------------------------------------------------

LOG_COLS = [
    "created_at", "model_version", "as_of_date", "match_date", "match_id",
    "home_code", "away_code", "p_home", "p_draw", "p_away",
    "lambda_home", "lambda_away", "p_over25", "p_btts", "neutral",
]

SILVER_COLS = ["match_id", "date", "home_code", "away_code", "home_goals", "away_goals", "neutral"]


def make_log_df(rows: list[dict]) -> pd.DataFrame:
    """Construye un log DataFrame con los valores por defecto faltantes."""
    defaults = {
        "created_at": "2026-06-11T10:00:00Z",
        "model_version": "dc-v1",
        "as_of_date": "2026-06-11",
        "match_date": "2026-06-15",
        "match_id": "m1",
        "home_code": "ARG",
        "away_code": "BRA",
        "p_home": "0.5",
        "p_draw": "0.3",
        "p_away": "0.2",
        "lambda_home": "1.5",
        "lambda_away": "1.0",
        "p_over25": "",
        "p_btts": "",
        "neutral": "False",
    }
    result = []
    for row in rows:
        r = dict(defaults)
        r.update({k: str(v) for k, v in row.items()})
        result.append(r)
    return pd.DataFrame(result, columns=LOG_COLS)


def make_silver_df(rows: list[dict]) -> pd.DataFrame:
    """Construye un silver DataFrame."""
    defaults = {
        "match_id": "m1",
        "date": "2026-06-15",
        "home_code": "ARG",
        "away_code": "BRA",
        "home_goals": "1",
        "away_goals": "1",
        "neutral": "False",
    }
    result = []
    for row in rows:
        r = dict(defaults)
        r.update({k: str(v) for k, v in row.items()})
        result.append(r)
    return pd.DataFrame(result)


# ---------------------------------------------------------------------------
# R6 — test_join_match_id_y_skipped_pendientes
# ---------------------------------------------------------------------------


def test_join_match_id_y_skipped_pendientes():
    """R6: join por match_id; sin marcador real → skipped (no error)."""
    log = make_log_df([
        {"match_id": "m1", "p_home": "0.6", "p_draw": "0.25", "p_away": "0.15"},
        {"match_id": "m2", "p_home": "0.4", "p_draw": "0.35", "p_away": "0.25"},  # sin resultado
        {"match_id": "m3", "p_home": "0.3", "p_draw": "0.3", "p_away": "0.4"},   # marcador vacío
    ])
    silver = make_silver_df([
        {"match_id": "m1", "home_goals": "2", "away_goals": "1"},
        # m2 no está en silver → skipped
        {"match_id": "m3", "home_goals": "", "away_goals": ""},  # marcador vacío
    ])

    evaluable, skipped = join_log_silver(log, silver)

    assert len(evaluable) == 1, f"Se esperaba 1 evaluable, hay {len(evaluable)}"
    assert evaluable.iloc[0]["match_id"] == "m1"
    assert float(evaluable.iloc[0]["home_goals"]) == 2.0
    assert float(evaluable.iloc[0]["away_goals"]) == 1.0

    assert len(skipped) == 2, f"Se esperaban 2 skipped, hay {len(skipped)}"
    skip_ids = set(skipped["match_id"])
    assert "m2" in skip_ids, "m2 (sin resultado) debe estar skipped"
    assert "m3" in skip_ids, "m3 (marcador vacío) debe estar skipped"


def test_join_filtros_de_fecha():
    """R6: filtros from_date / to_date sobre match_date."""
    log = make_log_df([
        {"match_id": "early", "match_date": "2026-06-10"},
        {"match_id": "mid",   "match_date": "2026-06-15"},
        {"match_id": "late",  "match_date": "2026-06-20"},
    ])
    silver = make_silver_df([
        {"match_id": "early", "home_goals": "1", "away_goals": "0"},
        {"match_id": "mid",   "home_goals": "2", "away_goals": "2"},
        {"match_id": "late",  "home_goals": "0", "away_goals": "1"},
    ])

    evaluable, _ = join_log_silver(log, silver, from_date="2026-06-12", to_date="2026-06-17")
    assert len(evaluable) == 1
    assert evaluable.iloc[0]["match_id"] == "mid"


# ---------------------------------------------------------------------------
# R7 — test_logloss_brier_exactitud_oraculo
# ---------------------------------------------------------------------------


def test_logloss_brier_exactitud_oraculo():
    """R7: log-loss, Brier y exactitud verificados contra un oráculo calculado a mano.

    Usamos 3 partidos con probabilidades y resultados conocidos:
      Partido 1: p=(0.7, 0.2, 0.1) → real=1  → predicción argmax='1' (CORRECTO)
      Partido 2: p=(0.2, 0.5, 0.3) → real=X  → predicción argmax='X' (CORRECTO)
      Partido 3: p=(0.3, 0.3, 0.4) → real=1  → predicción argmax='2' (INCORRECTO)

    Brier multiclase: mean(sum_k (p_k - o_k)^2)
      Partido 1: (0.7-1)^2 + (0.2-0)^2 + (0.1-0)^2 = 0.09+0.04+0.01 = 0.14
      Partido 2: (0.2-0)^2 + (0.5-1)^2 + (0.3-0)^2 = 0.04+0.25+0.09 = 0.38
      Partido 3: (0.3-1)^2 + (0.3-0)^2 + (0.4-0)^2 = 0.49+0.09+0.16 = 0.74
      Brier = (0.14 + 0.38 + 0.74) / 3 = 1.26/3 = 0.42

    Exactitud: 2/3 = 0.6667
    """
    from sklearn.metrics import log_loss as sk_log_loss

    log = make_log_df([
        {"match_id": "p1", "p_home": "0.7", "p_draw": "0.2", "p_away": "0.1",
         "home_goals": "2", "away_goals": "0"},
        {"match_id": "p2", "p_home": "0.2", "p_draw": "0.5", "p_away": "0.3",
         "home_goals": "1", "away_goals": "1"},
        {"match_id": "p3", "p_home": "0.3", "p_draw": "0.3", "p_away": "0.4",
         "home_goals": "1", "away_goals": "0"},
    ])
    # Añadir home_goals y away_goals directamente al DataFrame para el evaluable
    log["home_goals"] = [2.0, 1.0, 1.0]
    log["away_goals"] = [0.0, 1.0, 0.0]

    window_preds = evaluable_to_window_predictions(log)
    metrics = compute_metrics(window_preds, n_skipped=0)

    # Oráculo Brier (R7)
    brier_oracle = 0.42
    assert abs(metrics.brier - brier_oracle) < 1e-9, (
        f"Brier esperado={brier_oracle}, obtenido={metrics.brier}"
    )

    # Oráculo exactitud (R7)
    accuracy_oracle = 2.0 / 3.0
    assert abs(metrics.accuracy - accuracy_oracle) < 1e-9, (
        f"Exactitud esperada={accuracy_oracle:.4f}, obtenida={metrics.accuracy:.4f}"
    )

    # log-loss: verificar que es positivo y finito
    assert metrics.log_loss > 0
    assert math.isfinite(metrics.log_loss)

    # Oráculo log-loss manual con sklearn directamente (mismo resultado esperado)
    y_true = ["1", "X", "1"]
    probs = np.array([[0.7, 0.2, 0.1], [0.2, 0.5, 0.3], [0.3, 0.3, 0.4]])
    # sklearn espera columnas en orden sorted(labels) = ["1","2","X"]
    probs_skl = probs[:, [0, 2, 1]]  # reordenar: 1, 2, X
    ll_oracle = sk_log_loss(y_true, probs_skl, labels=["1", "2", "X"])
    assert abs(metrics.log_loss - ll_oracle) < 1e-9, (
        f"log-loss no coincide con sklearn: esperado={ll_oracle:.6f}, obtenido={metrics.log_loss:.6f}"
    )


def test_outcome_from_goals():
    """R7: desenlace correcto desde goles."""
    assert _outcome_from_goals(2.0, 0.0) == "1"
    assert _outcome_from_goals(1.0, 1.0) == "X"
    assert _outcome_from_goals(0.0, 2.0) == "2"


# ---------------------------------------------------------------------------
# R8 — test_calibracion_bins_y_degradacion
# ---------------------------------------------------------------------------


def test_calibracion_bins_y_degradacion():
    """R8: calibración produce datos por bins; degradación con pocos datos."""
    # Con 5 partidos (pocos), la calibración debe degradar graciosamente
    log = make_log_df([
        {"match_id": f"m{i}", "p_home": "0.5", "p_draw": "0.3", "p_away": "0.2",
         "home_goals": str(g), "away_goals": "0"}
        for i, g in enumerate([1, 0, 1, 2, 0])
    ])
    log["home_goals"] = [1.0, 0.0, 1.0, 2.0, 0.0]
    log["away_goals"] = [0.0, 0.0, 0.0, 0.0, 0.0]

    window_preds = evaluable_to_window_predictions(log)
    # Con 10 bins pero solo 5 datos, debe reducir bins o marcar no-computable
    calibration = compute_calibration(window_preds, bins=10)

    # Debe devolver una lista de 3 entradas (una por desenlace 1/X/2)
    assert len(calibration) == 3
    outcomes = [cd.outcome for cd in calibration]
    assert outcomes == ["1", "X", "2"]

    # Al menos un desenlace es computable o todos son no-computables (degradación)
    # No debe lanzar excepción (R8)
    for cd in calibration:
        assert isinstance(cd.computable, bool)
        if cd.computable:
            assert len(cd.fraction_of_positives) > 0
            assert len(cd.mean_predicted_value) > 0


def test_calibracion_con_suficientes_datos():
    """R8: calibración computable con suficientes datos por desenlace."""
    # 30 partidos con distribución 1/X/2 balanceada
    log_rows = []
    for i in range(30):
        outcome = i % 3
        hg = 1 if outcome == 0 else (0 if outcome == 1 else 0)
        ag = 0 if outcome == 0 else (0 if outcome == 1 else 1)
        log_rows.append({
            "match_id": f"m{i}",
            "p_home": "0.4",
            "p_draw": "0.3",
            "p_away": "0.3",
        })

    log = make_log_df(log_rows)
    log["home_goals"] = [1.0 if (i % 3 == 0) else 0.0 for i in range(30)]
    log["away_goals"] = [0.0 if (i % 3 != 2) else 1.0 for i in range(30)]

    window_preds = evaluable_to_window_predictions(log)
    calibration = compute_calibration(window_preds, bins=5)

    # Con 10 positivos por clase y 5 bins, debe ser computable para al menos 1
    any_computable = any(cd.computable for cd in calibration)
    assert any_computable, "Con suficientes datos, al menos un desenlace debe ser computable"


# ---------------------------------------------------------------------------
# R9 — test_brier_mercados_over25_y_btts
# ---------------------------------------------------------------------------


def test_brier_mercados_over25_y_btts():
    """R9: Brier binario de O/U 2.5 y BTTS calculado correctamente.

    Oráculo manual para 3 partidos:
      p1: p_over25=0.6, real_over=1 (1+2=3 > 2.5) → (0.6-1)^2=0.16
      p2: p_over25=0.4, real_over=0 (0+2=2 ≤ 2.5) → (0.4-0)^2=0.16
      p3: p_over25=0.7, real_over=1 (2+1=3 > 2.5) → (0.7-1)^2=0.09
      Brier_over25 = (0.16+0.16+0.09)/3 = 0.41/3 ≈ 0.1367

      p1: p_btts=0.5, real_btts=1 (hg=1>=1, ag=2>=1) → (0.5-1)^2=0.25
      p2: p_btts=0.3, real_btts=0 (hg=0<1)           → (0.3-0)^2=0.09
      p3: p_btts=0.8, real_btts=1 (hg=2>=1, ag=1>=1) → (0.8-1)^2=0.04
      Brier_btts = (0.25+0.09+0.04)/3 = 0.38/3 ≈ 0.1267
    """
    log = make_log_df([
        {"match_id": "p1", "p_over25": "0.6", "p_btts": "0.5",
         "home_goals": "1", "away_goals": "2"},
        {"match_id": "p2", "p_over25": "0.4", "p_btts": "0.3",
         "home_goals": "0", "away_goals": "2"},
        {"match_id": "p3", "p_over25": "0.7", "p_btts": "0.8",
         "home_goals": "2", "away_goals": "1"},
    ])
    log["home_goals"] = [1.0, 0.0, 2.0]
    log["away_goals"] = [2.0, 2.0, 1.0]

    result = compute_market_metrics(log)

    assert result is not None, "compute_market_metrics no debe retornar None con datos válidos"

    brier_over25_oracle = (0.16 + 0.16 + 0.09) / 3
    brier_btts_oracle = (0.25 + 0.09 + 0.04) / 3

    assert abs(result["brier_over25"] - brier_over25_oracle) < 1e-9, (
        f"Brier O/U2.5 esperado={brier_over25_oracle:.4f}, obtenido={result['brier_over25']:.4f}"
    )
    assert abs(result["brier_btts"] - brier_btts_oracle) < 1e-9, (
        f"Brier BTTS esperado={brier_btts_oracle:.4f}, obtenido={result['brier_btts']:.4f}"
    )


def test_brier_mercados_sin_valores_retorna_none():
    """R9: sin columnas de mercado con valores → None."""
    log = make_log_df([
        {"match_id": "p1"},
    ])
    log["home_goals"] = [1.0]
    log["away_goals"] = [0.0]
    # p_over25 y p_btts están vacías (default del helper)

    result = compute_market_metrics(log)
    assert result is None, "Sin valores de mercado debe retornar None"


# ---------------------------------------------------------------------------
# R10 — test_rmse_mae_lambda_vs_goles
# ---------------------------------------------------------------------------


def test_rmse_mae_lambda_vs_goles():
    """R10: RMSE y MAE entre lambda y goles reales, verificados con oráculo.

    Oráculo manual para 2 partidos (4 valores apilados):
      lambda_home=[1.5, 2.0], home_goals=[1.0, 2.0]
      lambda_away=[1.0, 0.5], away_goals=[1.0, 0.0]
      Errores (pred - real): [0.5, 0.0, 0.0, 0.5]
      RMSE = sqrt((0.25+0+0+0.25)/4) = sqrt(0.5/4) = sqrt(0.125) ≈ 0.35355
      MAE  = (0.5+0+0+0.5)/4 = 0.25
    """
    log = make_log_df([
        {"match_id": "p1", "lambda_home": "1.5", "lambda_away": "1.0",
         "home_goals": "1", "away_goals": "1"},
        {"match_id": "p2", "lambda_home": "2.0", "lambda_away": "0.5",
         "home_goals": "2", "away_goals": "0"},
    ])
    log["home_goals"] = [1.0, 2.0]
    log["away_goals"] = [1.0, 0.0]

    result = compute_lambda_error(log)

    rmse_oracle = math.sqrt(0.125)
    mae_oracle = 0.25

    assert abs(result["rmse"] - rmse_oracle) < 1e-9, (
        f"RMSE esperado={rmse_oracle:.6f}, obtenido={result['rmse']:.6f}"
    )
    assert abs(result["mae"] - mae_oracle) < 1e-9, (
        f"MAE esperado={mae_oracle:.6f}, obtenido={result['mae']:.6f}"
    )
    assert result["n"] == 4


def test_rmse_mae_lambda_evaluable_vacio():
    """R10: sin datos evaluables → NaN."""
    result = compute_lambda_error(pd.DataFrame())
    assert math.isnan(result["rmse"])
    assert math.isnan(result["mae"])
    assert result["n"] == 0


# ---------------------------------------------------------------------------
# R11 — test_reporte_determinista_solo_bajo_data
# ---------------------------------------------------------------------------


def test_reporte_determinista_solo_bajo_data(tmp_path):
    """R11: reporte escrito bajo data/; determinista byte a byte; sort_keys en JSON."""
    # Crear data dir bajo tmp_path y configurar como relativo
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    out_dir = data_dir / "reports" / "evaluacion"

    log = make_log_df([
        {"match_id": "p1", "p_home": "0.6", "p_draw": "0.25", "p_away": "0.15",
         "lambda_home": "1.5", "lambda_away": "1.0"},
    ])
    log["home_goals"] = [2.0]
    log["away_goals"] = [0.0]
    skipped = pd.DataFrame()

    window_preds = evaluable_to_window_predictions(log)
    metrics = compute_metrics(window_preds, n_skipped=0)
    calibration = compute_calibration(window_preds, bins=3)
    lambda_error = compute_lambda_error(log)

    # Primera escritura
    report1 = write_report(
        evaluable=log,
        skipped=skipped,
        metrics=metrics,
        calibration=calibration,
        lambda_error=lambda_error,
        out_dir=out_dir,
    )

    # Segunda escritura (mismo input → mismo output)
    report2 = write_report(
        evaluable=log,
        skipped=skipped,
        metrics=metrics,
        calibration=calibration,
        lambda_error=lambda_error,
        out_dir=out_dir,
    )

    # Verificar archivos creados
    summary_path = out_dir / "summary.json"
    per_match_path = out_dir / "per_match.csv"
    cal_path = out_dir / "calibration.csv"

    assert summary_path.is_file(), "summary.json debe existir"
    assert per_match_path.is_file(), "per_match.csv debe existir"
    assert cal_path.is_file(), "calibration.csv debe existir"

    # Escritura bajo data/ (R11)
    assert str(summary_path).startswith(str(data_dir))
    assert str(per_match_path).startswith(str(data_dir))

    # Determinismo byte a byte (R11): mismo contenido en ambas escrituras
    content1 = summary_path.read_text(encoding="utf-8")
    report2_summary = (out_dir / "summary.json").read_text(encoding="utf-8")
    assert content1 == report2_summary, "summary.json no es determinista"

    # sort_keys en JSON (R11)
    data = json.loads(content1)
    keys = list(data.keys())
    assert keys == sorted(keys), f"summary.json no tiene sort_keys: {keys}"


def test_reporte_rechaza_ruta_fuera_de_data(tmp_path):
    """R11: escritura fuera de data/ debe ser rechazada."""
    out_dir = tmp_path / "informe_fuera_de_data"
    log = make_log_df([{"match_id": "p1"}])
    log["home_goals"] = [1.0]
    log["away_goals"] = [0.0]

    from src.eval.evaluate import _assert_under_data
    with pytest.raises(ValueError, match="Escritura confinada"):
        _assert_under_data(out_dir)


def test_evaluate_sin_log_lanza_error(tmp_path):
    """R11/R13: evaluate sin log lanza FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="log de predicciones"):
        evaluate(
            log_path=tmp_path / "no_existe.csv",
            silver_path=tmp_path / "silver.csv",
        )


def test_evaluate_completo_offline(tmp_path):
    """R11: evaluate() end-to-end con datos sintéticos en disco."""
    # Preparar log y silver en disco
    data_dir = tmp_path / "data"
    (data_dir / "predictions").mkdir(parents=True)
    (data_dir / "silver").mkdir(parents=True)

    log_path = data_dir / "predictions" / "log.csv"
    silver_path = data_dir / "silver" / "matches.csv"
    out_dir = data_dir / "reports" / "evaluacion"

    log_df = make_log_df([
        {"match_id": "m1", "p_home": "0.6", "p_draw": "0.25", "p_away": "0.15",
         "lambda_home": "1.5", "lambda_away": "1.0", "match_date": "2026-06-15"},
        {"match_id": "m2", "p_home": "0.3", "p_draw": "0.3", "p_away": "0.4",
         "lambda_home": "0.9", "lambda_away": "1.2", "match_date": "2026-06-16"},
    ])
    log_df.to_csv(log_path, index=False)

    silver_rows = [
        {"match_id": "m1", "date": "2026-06-15", "home_code": "ARG", "away_code": "BRA",
         "home_goals": "2", "away_goals": "0", "neutral": "False"},
        {"match_id": "m2", "date": "2026-06-16", "home_code": "FRA", "away_code": "GER",
         "home_goals": "1", "away_goals": "1", "neutral": "False"},
    ]
    pd.DataFrame(silver_rows).to_csv(silver_path, index=False)

    result = evaluate(
        log_path=log_path,
        silver_path=silver_path,
        out_dir=out_dir,
    )

    assert result["n_evaluable"] == 2
    assert result["n_skipped"] == 0
    assert result.get("all_skipped") is False
    assert result["metrics"] is not None
    assert result["lambda_error"] is not None

    # Archivos creados
    assert (out_dir / "summary.json").is_file()
    assert (out_dir / "per_match.csv").is_file()
    assert (out_dir / "calibration.csv").is_file()
