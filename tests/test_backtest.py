"""Feature 5 — backtesting (R1–R9, R13).

Tests 100 % offline y deterministas. Usan datasets sinteticos pequenos (rapidos)
para los tests con fit real. Sin red, sin reloj. Los tests con fit usan 3-4 equipos
y ~50-100 partidos para que el refit sea rapido.
"""

from __future__ import annotations

import csv
import io
import json
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers para datasets sinteticos pequenos
# ---------------------------------------------------------------------------

TEAMS = ["AAA", "BBB", "CCC", "DDD"]

_DATE_START = "2020-01-01"


def _make_silver_csv(
    n_per_pair: int = 8,
    extra_rows: list[dict] | None = None,
    path: Path | None = None,
) -> tuple[str, list[dict]]:
    """Crea un CSV silver sintetico con TEAMS cruzados.

    Args:
        n_per_pair: Number of matches per ordered team pair.
        extra_rows: Additional rows to append (e.g. future matches for anti-leakage).
        path: If provided, writes the CSV to this path.

    Returns:
        Tuple of (CSV text, list of row dicts).
    """
    import itertools
    from datetime import date, timedelta

    rows = []
    match_id = 1
    current_date = date.fromisoformat(_DATE_START)
    for home, away in itertools.permutations(TEAMS, 2):
        for i in range(n_per_pair):
            rows.append(
                {
                    "match_id": match_id,
                    "date": current_date.isoformat(),
                    "home_code": home,
                    "away_code": away,
                    "home_goals": (match_id % 3),
                    "away_goals": ((match_id + 1) % 3),
                    "neutral": "False",
                }
            )
            match_id += 1
            current_date += timedelta(days=7)

    if extra_rows:
        rows.extend(extra_rows)

    header = "match_id,date,home_code,away_code,home_goals,away_goals,neutral"
    lines = [header] + [
        f"{r['match_id']},{r['date']},{r['home_code']},{r['away_code']},"
        f"{r['home_goals']},{r['away_goals']},{r['neutral']}"
        for r in rows
    ]
    csv_text = "\n".join(lines) + "\n"
    if path is not None:
        path.write_text(csv_text, encoding="utf-8")
    return csv_text, rows


# ---------------------------------------------------------------------------
# R1 — test_ventanas_month_week_y_rango
# ---------------------------------------------------------------------------


def test_ventanas_month_week_y_rango(tmp_path):
    """R1: las ventanas se generan en limites de mes/semana sin reloj, dentro del rango."""
    from src.backtest.walkforward import BacktestConfig, _generate_window_starts
    from datetime import date

    # Ventanas mensuales: 3 meses
    starts_m = _generate_window_starts(
        date(2024, 1, 1), date(2024, 4, 1), "month"
    )
    assert len(starts_m) == 3
    assert all(d.day == 1 for d in starts_m)
    assert starts_m[0] == date(2024, 1, 1)
    assert starts_m[1] == date(2024, 2, 1)
    assert starts_m[2] == date(2024, 3, 1)

    # Ventanas semanales: entre lunes y lunes siguiente
    starts_w = _generate_window_starts(
        date(2024, 1, 1), date(2024, 1, 22), "week"
    )
    assert len(starts_w) >= 3
    for d in starts_w:
        assert d.weekday() == 0, f"{d} no es lunes"

    # Ninguna fecha fuera del rango
    for d in starts_m:
        assert d < date(2024, 4, 1)
    for d in starts_w:
        assert d < date(2024, 1, 22)


# ---------------------------------------------------------------------------
# R2 — test_anti_fuga_mutar_futuro_no_cambia_predicciones
# ---------------------------------------------------------------------------


def test_anti_fuga_mutar_futuro_no_cambia_predicciones(tmp_path):
    """R2: alterar partidos POSTERIORES a una ventana no cambia sus predicciones (tol 1e-12).

    Incluye el caso limite: filas con date EXACTAMENTE igual a as_of_date (2024-01-01)
    tambien deben quedar excluidas del entrenamiento (filtro ``date < as_of_date``, no ``<=``).
    Una implementacion con ``<=`` pasaria el caso posterior pero fallaria este limite.
    """
    from datetime import date as date_t

    from src.backtest.walkforward import BacktestConfig, run

    silver_base = tmp_path / "matches_base.csv"
    silver_mutado_posterior = tmp_path / "matches_mutado_posterior.csv"
    silver_mutado_limite = tmp_path / "matches_mutado_limite.csv"

    # Dataset base: n_per_pair=20 da fechas 2020-2024.
    # Ademas se injectan dos filas en 2024-01-01 (el caso limite exacto) que
    # representan partidos de ENTRENAMIENTO pasado (no se evaluan porque
    # la ventana de evaluacion empieza en 2024-01-01 y el filtro de entrenamiento
    # es ``date < as_of_date``; con ``<=`` estas filas entrarian al fit).
    extra_rows_limite = [
        {
            "match_id": 9001,
            "date": "2024-01-01",
            "home_code": "AAA",
            "away_code": "BBB",
            "home_goals": 1,
            "away_goals": 0,
            "neutral": "False",
        },
        {
            "match_id": 9002,
            "date": "2024-01-01",
            "home_code": "CCC",
            "away_code": "DDD",
            "home_goals": 2,
            "away_goals": 1,
            "neutral": "False",
        },
    ]
    _make_silver_csv(n_per_pair=20, extra_rows=extra_rows_limite, path=silver_base)
    df = pd.read_csv(silver_base)

    # --- Mutacion A: filas con fecha >= 2024-02-01 (posterior a la primera ventana enero) ---
    df_mutado_post = df.copy()
    mask_posterior = df_mutado_post["date"] >= "2024-02-01"
    assert mask_posterior.any(), "El fixture debe tener filas posteriores a 2024-02-01"
    df_mutado_post.loc[mask_posterior, "home_goals"] = 99
    df_mutado_post.loc[mask_posterior, "away_goals"] = 99
    df_mutado_post.to_csv(silver_mutado_posterior, index=False)

    # --- Mutacion B (caso limite): filas con date EXACTAMENTE igual a as_of_date ---
    # as_of_date de la primera ventana = 2024-01-01 (from_date)
    # El filtro correcto es ``date < as_of_date``; con ``<=`` estas filas entrarian al
    # entrenamiento y las predicciones diferirían.
    df_mutado_lim = df.copy()
    mask_limite = df_mutado_lim["date"] == "2024-01-01"
    assert mask_limite.any(), "El fixture debe tener al menos una fila con date=2024-01-01"
    df_mutado_lim.loc[mask_limite, "home_goals"] = 99
    df_mutado_lim.loc[mask_limite, "away_goals"] = 99
    df_mutado_lim.to_csv(silver_mutado_limite, index=False)

    # Configuracion comun: evaluar solo enero 2024
    def _cfg(silver: Path) -> BacktestConfig:
        return BacktestConfig(
            from_date="2024-01-01",
            to_date="2024-01-31",
            refit_every="month",
            silver_path=silver,
            out_dir=tmp_path / "out",
        )

    results_base, _ = run(_cfg(silver_base))
    results_post, _ = run(_cfg(silver_mutado_posterior))
    results_lim, _ = run(_cfg(silver_mutado_limite))

    preds_base = [p for wr in results_base for p in wr.predictions]
    preds_post = [p for wr in results_post for p in wr.predictions]
    preds_lim = [p for wr in results_lim for p in wr.predictions]

    assert len(preds_base) == len(preds_post), (
        f"Mutacion posterior cambio el numero de predicciones: "
        f"base={len(preds_base)}, mutado={len(preds_post)}"
    )
    assert len(preds_base) == len(preds_lim), (
        f"Mutacion limite cambio el numero de predicciones: "
        f"base={len(preds_base)}, mutado={len(preds_lim)}"
    )

    for pb, pp in zip(preds_base, preds_post):
        assert abs(pb.prob_home - pp.prob_home) < 1e-12, (
            "Mutacion POSTERIOR: prob_home difiere (fuga de futuro)"
        )
        assert abs(pb.prob_draw - pp.prob_draw) < 1e-12, (
            "Mutacion POSTERIOR: prob_draw difiere (fuga de futuro)"
        )
        assert abs(pb.prob_away - pp.prob_away) < 1e-12, (
            "Mutacion POSTERIOR: prob_away difiere (fuga de futuro)"
        )

    for pb, pl in zip(preds_base, preds_lim):
        assert abs(pb.prob_home - pl.prob_home) < 1e-12, (
            "Mutacion LIMITE (date==as_of_date): prob_home difiere — "
            "el filtro usa <= en lugar de < (fuga de datos en el borde)"
        )
        assert abs(pb.prob_draw - pl.prob_draw) < 1e-12, (
            "Mutacion LIMITE (date==as_of_date): prob_draw difiere — "
            "el filtro usa <= en lugar de < (fuga de datos en el borde)"
        )
        assert abs(pb.prob_away - pl.prob_away) < 1e-12, (
            "Mutacion LIMITE (date==as_of_date): prob_away difiere — "
            "el filtro usa <= en lugar de < (fuga de datos en el borde)"
        )


# ---------------------------------------------------------------------------
# R3 — test_refits_reales_y_skipped_con_motivo
# ---------------------------------------------------------------------------


def test_refits_reales_y_skipped_con_motivo(tmp_path):
    """R3: refits reales por ventana; partidos con equipos fuera del recorte → skipped."""
    from src.backtest.walkforward import BacktestConfig, run

    # Dataset pequeno solo con AAA y BBB; incluir partido de CCC que no estara entrenado
    header = "match_id,date,home_code,away_code,home_goals,away_goals,neutral"
    # 30 partidos historicos (2020-2023) con AAA vs BBB
    from datetime import date, timedelta

    rows_hist = []
    cur = date(2020, 1, 1)
    for i in range(60):
        rows_hist.append(
            f"{i+1},{cur.isoformat()},AAA,BBB,{i%3},{(i+1)%3},False"
        )
        cur += timedelta(days=7)
        rows_hist.append(
            f"{i+61},{cur.isoformat()},BBB,AAA,{i%3},{(i+1)%3},False"
        )
        cur += timedelta(days=7)

    # Partido de evaluacion: AAA vs BBB (conocido) y ZZZ vs WWW (desconocidos)
    rows_eval = [
        "201,2024-01-15,AAA,BBB,1,0,False",  # evaluable
        "202,2024-01-20,ZZZ,WWW,2,1,False",  # skipped: equipos fuera de recorte
    ]

    csv_text = "\n".join([header] + rows_hist + rows_eval) + "\n"
    silver = tmp_path / "matches.csv"
    silver.write_text(csv_text, encoding="utf-8")

    cfg = BacktestConfig(
        from_date="2024-01-01",
        to_date="2024-01-31",
        refit_every="month",
        silver_path=silver,
        out_dir=tmp_path / "out",
    )

    results, _ = run(cfg)
    assert len(results) >= 1

    # Al menos un partido evaluable y uno skipped
    total_preds = sum(len(wr.predictions) for wr in results)
    total_skipped = sum(len(wr.skipped) for wr in results)

    assert total_preds >= 1, "Debe haber al menos 1 prediccion (AAA vs BBB)"
    assert total_skipped >= 1, "Debe haber al menos 1 skipped (ZZZ vs WWW)"

    # Los skipped tienen motivo no vacio
    for wr in results:
        for sk in wr.skipped:
            assert sk.reason, f"Skipped sin motivo: {sk}"

    # El refit uso los datos reales (n_train > 0)
    for wr in results:
        if wr.predictions:
            assert wr.n_train > 0


# ---------------------------------------------------------------------------
# R4 — test_logloss_brier_exactitud_oraculo_a_mano
# ---------------------------------------------------------------------------


def test_logloss_brier_exactitud_oraculo_a_mano():
    """R4: oraculo a mano con probs conocidas verifica log-loss, Brier y exactitud."""
    from src.backtest.metrics import OUTCOME_ORDER, compute_metrics
    from src.backtest.walkforward import WindowPrediction

    # 3 partidos con probs exactas y resultados conocidos
    preds = [
        WindowPrediction(
            date="2024-01-01", home_code="AAA", away_code="BBB",
            prob_home=0.7, prob_draw=0.2, prob_away=0.1,
            actual="1",
            marginal_home=1/3, marginal_draw=1/3, marginal_away=1/3,
        ),
        WindowPrediction(
            date="2024-01-02", home_code="CCC", away_code="DDD",
            prob_home=0.3, prob_draw=0.4, prob_away=0.3,
            actual="X",
            marginal_home=1/3, marginal_draw=1/3, marginal_away=1/3,
        ),
        WindowPrediction(
            date="2024-01-03", home_code="AAA", away_code="CCC",
            prob_home=0.2, prob_draw=0.3, prob_away=0.5,
            actual="2",
            marginal_home=1/3, marginal_draw=1/3, marginal_away=1/3,
        ),
    ]

    result = compute_metrics(preds, n_skipped=0)

    # Log-loss oraculo: -mean(log(p_correct))
    # p_correct: 0.7, 0.4, 0.5
    ll_oracle = -(math.log(0.7) + math.log(0.4) + math.log(0.5)) / 3
    assert abs(result.log_loss - ll_oracle) < 1e-9, (
        f"log_loss={result.log_loss}, oracle={ll_oracle}"
    )

    # Brier oraculo: (1/3) * sum_i sum_k (p_ik - o_ik)^2
    # Partido 1 (actual=1): (0.7-1)^2 + (0.2-0)^2 + (0.1-0)^2 = 0.09+0.04+0.01 = 0.14
    # Partido 2 (actual=X): (0.3-0)^2 + (0.4-1)^2 + (0.3-0)^2 = 0.09+0.36+0.09 = 0.54
    # Partido 3 (actual=2): (0.2-0)^2 + (0.3-0)^2 + (0.5-1)^2 = 0.04+0.09+0.25 = 0.38
    brier_oracle = (0.14 + 0.54 + 0.38) / 3
    assert abs(result.brier - brier_oracle) < 1e-9, (
        f"brier={result.brier}, oracle={brier_oracle}"
    )

    # Exactitud: argmax correcto en los 3 (pred: "1", "X", "2" = todos correctos)
    assert abs(result.accuracy - 1.0) < 1e-9

    assert result.n_matches == 3
    assert result.n_skipped == 0


# ---------------------------------------------------------------------------
# R5 — test_calibracion_bins_y_degradacion
# ---------------------------------------------------------------------------


def test_calibracion_bins_y_degradacion():
    """R5: calibracion produce CalibrationData; con clase escasa, reduce bins o marca no computable."""
    from src.backtest.metrics import compute_calibration
    from src.backtest.walkforward import WindowPrediction

    # 10 predicciones: mayoría "1", 1 "X", 0 "2" → clase "2" sin samples
    preds = []
    for i in range(8):
        preds.append(WindowPrediction(
            date=f"2024-01-{i+1:02d}", home_code="A", away_code="B",
            prob_home=0.6 + i * 0.01, prob_draw=0.3, prob_away=0.1,
            actual="1",
            marginal_home=0.5, marginal_draw=0.3, marginal_away=0.2,
        ))
    preds.append(WindowPrediction(
        date="2024-01-09", home_code="A", away_code="C",
        prob_home=0.3, prob_draw=0.5, prob_away=0.2,
        actual="X",
        marginal_home=0.5, marginal_draw=0.3, marginal_away=0.2,
    ))
    preds.append(WindowPrediction(
        date="2024-01-10", home_code="B", away_code="C",
        prob_home=0.4, prob_draw=0.3, prob_away=0.3,
        actual="1",
        marginal_home=0.5, marginal_draw=0.3, marginal_away=0.2,
    ))

    # Con bins=10: clase "2" tiene 0 muestras → computable=False
    calib = compute_calibration(preds, bins=10)
    assert len(calib) == 3

    calib_dict = {c.outcome: c for c in calib}

    # Clase "2" sin positivos: no computable
    assert not calib_dict["2"].computable

    # Clase "1" con 9 positivos (mayor que 2): computable
    assert calib_dict["1"].computable
    assert len(calib_dict["1"].fraction_of_positives) > 0

    # No aborta aunque haya clases escasas
    assert calib_dict["X"].computable is not None  # solo que devuelve algo


# ---------------------------------------------------------------------------
# R6 — test_baselines_uniforme_y_marginal
# ---------------------------------------------------------------------------


def test_baselines_uniforme_y_marginal():
    """R6: baselines uniforme y marginal calculados con el mismo protocolo; metricas comparables."""
    from src.backtest.metrics import (
        compute_metrics,
        make_marginal_probs,
        make_uniform_probs,
    )
    from src.backtest.walkforward import WindowPrediction

    preds = [
        WindowPrediction(
            date=f"2024-01-{i+1:02d}", home_code="A", away_code="B",
            prob_home=0.5, prob_draw=0.25, prob_away=0.25,
            actual=["1", "X", "2"][i % 3],
            marginal_home=0.45, marginal_draw=0.30, marginal_away=0.25,
        )
        for i in range(9)
    ]
    n = len(preds)

    # Uniforme: todas las probs = 1/3
    uni_probs = make_uniform_probs(n)
    assert uni_probs.shape == (n, 3)
    assert abs(uni_probs[0, 0] - 1 / 3) < 1e-12

    # Marginal: probs de cada prediccion (0.45/0.30/0.25)
    marg_probs = make_marginal_probs(preds)
    assert marg_probs.shape == (n, 3)
    assert abs(marg_probs[0, 0] - 0.45) < 1e-12

    # Las tres metricas son calculables con las mismas funciones
    m_model = compute_metrics(preds, n_skipped=0)
    m_uniform = compute_metrics(preds, n_skipped=0, probs_override=uni_probs)
    m_marginal = compute_metrics(preds, n_skipped=0, probs_override=marg_probs)

    # Todas tienen n_matches
    assert m_model.n_matches == n
    assert m_uniform.n_matches == n
    assert m_marginal.n_matches == n

    # El uniforme tiene log-loss teorico = log(3)
    assert abs(m_uniform.log_loss - math.log(3)) < 1e-6

    # Brier uniforme: cada partido (p_k - o_k)^2 = (1/3-1)^2 + (1/3-0)^2 + (1/3-0)^2 = 2/3
    assert abs(m_uniform.brier - 2 / 3) < 1e-6


# ---------------------------------------------------------------------------
# R7 — test_grid_ranking_orden_y_solo_con_flag
# ---------------------------------------------------------------------------


def test_grid_ranking_orden_y_solo_con_flag(tmp_path):
    """R7: grid ordena por (log_loss, brier); sin --grid no ejecuta busqueda."""
    from src.backtest.report import run_grid
    from src.backtest.walkforward import BacktestConfig

    # Dataset sintetico
    silver = tmp_path / "matches.csv"
    _make_silver_csv(n_per_pair=20, path=silver)

    cfg = BacktestConfig(
        from_date="2024-01-01",
        to_date="2024-02-28",
        refit_every="month",
        silver_path=silver,
        out_dir=tmp_path / "out",
    )

    # Con grid: devuelve ranking ordenado
    ranking = run_grid(cfg, xis=[0.5, 0.8], reg_lambdas=[0.5, 1.0])

    if len(ranking) >= 2:
        for i in range(len(ranking) - 1):
            a, b = ranking[i], ranking[i + 1]
            assert (a["log_loss"], a["brier"]) <= (b["log_loss"], b["brier"]), (
                f"Ranking no ordenado: {a} > {b}"
            )

    # Cada entrada tiene las claves esperadas
    for entry in ranking:
        assert "xi" in entry
        assert "reg_lambda" in entry
        assert "log_loss" in entry
        assert "brier" in entry


def test_grid_no_ejecuta_sin_flag(tmp_path):
    """R7: sin --grid el informe no incluye grid_ranking."""
    from src.backtest.report import write_report
    from src.backtest.walkforward import BacktestConfig

    silver = tmp_path / "matches.csv"
    _make_silver_csv(n_per_pair=20, path=silver)

    cfg = BacktestConfig(
        from_date="2024-01-01",
        to_date="2024-02-28",
        refit_every="month",
        silver_path=silver,
        out_dir=tmp_path / "out",
    )

    summary = write_report(cfg, run_grid_flag=False)
    assert "grid_ranking" not in summary, "grid_ranking no debe aparecer sin --grid"


# ---------------------------------------------------------------------------
# R8 — test_roi_value_bets_oraculo
# ---------------------------------------------------------------------------


def test_roi_value_bets_oraculo(tmp_path):
    """R8: oraculo a mano para ROI con value bets conocidos."""
    from src.backtest.roi import evaluate_roi
    from src.backtest.walkforward import WindowPrediction

    # 2 partidos: en el primero hay value bet en "1" (prob=0.7, odds=1.8 → 0.7*1.8=1.26 > 1.05)
    # En el segundo no hay value (prob=0.3, odds=2.0 → 0.3*2.0=0.6 < 1.05)
    preds = [
        WindowPrediction(
            date="2024-01-15", home_code="AAA", away_code="BBB",
            prob_home=0.70, prob_draw=0.20, prob_away=0.10,
            actual="1",  # acierto
            marginal_home=0.4, marginal_draw=0.3, marginal_away=0.3,
        ),
        WindowPrediction(
            date="2024-01-22", home_code="CCC", away_code="DDD",
            prob_home=0.30, prob_draw=0.40, prob_away=0.30,
            actual="X",  # no hay value bet para ninguno
            marginal_home=0.4, marginal_draw=0.3, marginal_away=0.3,
        ),
    ]

    odds_csv = tmp_path / "odds.csv"
    odds_csv.write_text(
        "date,home_code,away_code,odds_home,odds_draw,odds_away\n"
        "2024-01-15,AAA,BBB,1.80,3.50,6.00\n"  # value en "1": 0.7*1.8=1.26>1.05 ✓
        "2024-01-22,CCC,DDD,2.00,2.20,3.00\n",  # sin value (max: 0.4*2.2=0.88)
        encoding="utf-8",
    )

    result = evaluate_roi(preds, odds_csv, value_threshold=0.05)
    assert result is not None
    assert result.n_bets == 1
    assert result.n_wins == 1
    assert abs(result.stake - 1.0) < 1e-9
    assert abs(result.retorno - 1.80) < 1e-9
    assert abs(result.roi - 0.80) < 1e-6


def test_roi_sin_csv_omitido(tmp_path):
    """R8: sin CSV de cuotas, ROI se omite con aviso (sin fallo)."""
    from src.backtest.roi import evaluate_roi
    from src.backtest.walkforward import WindowPrediction

    preds = [
        WindowPrediction(
            date="2024-01-15", home_code="A", away_code="B",
            prob_home=0.5, prob_draw=0.3, prob_away=0.2,
            actual="1",
            marginal_home=0.4, marginal_draw=0.3, marginal_away=0.3,
        )
    ]
    ruta_inexistente = tmp_path / "no_existe.csv"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = evaluate_roi(preds, ruta_inexistente)

    assert result is None
    assert any("omite" in str(w.message).lower() or "roi" in str(w.message).lower()
               for w in caught)


def test_roi_descartes_malformados(tmp_path):
    """R8: filas con cuotas <= 1.0 o fecha invalida se descartan con conteo."""
    from src.backtest.roi import evaluate_roi, load_odds
    from src.backtest.walkforward import WindowPrediction

    odds_csv = tmp_path / "odds_mal.csv"
    odds_csv.write_text(
        "date,home_code,away_code,odds_home,odds_draw,odds_away\n"
        "2024-01-15,AAA,BBB,0.90,3.50,6.00\n"   # descarte: odds_home <= 1.0
        "2024-01-16,CCC,DDD,abc,3.50,6.00\n"    # descarte: no numerico
        "2024-01-17,EEE,FFF,1.80,3.50,6.00\n",  # valida
        encoding="utf-8",
    )

    loaded = load_odds(odds_csv)
    assert loaded is not None
    valid_rows, n_descartes = loaded
    assert n_descartes == 2
    assert len(valid_rows) == 1


# ---------------------------------------------------------------------------
# R9 — test_reporte_determinista_mismo_contenido
# ---------------------------------------------------------------------------


def test_reporte_determinista_mismo_contenido(tmp_path):
    """R9: mismas entradas → metricas y archivos identicos (determinismo completo).

    Los dos runs usan el mismo out_dir para que la configuracion sea identica byte
    a byte. El JSON resultante debe coincidir en su totalidad.
    """
    from src.backtest.report import write_report
    from src.backtest.walkforward import BacktestConfig

    silver = tmp_path / "matches.csv"
    _make_silver_csv(n_per_pair=20, path=silver)

    # Mismo out_dir: las unicas diferencias posibles son RNG o reloj (R9)
    out_dir = tmp_path / "out"

    cfg = BacktestConfig(
        from_date="2024-01-01",
        to_date="2024-02-28",
        refit_every="month",
        silver_path=silver,
        out_dir=out_dir,
    )

    write_report(cfg)
    j1 = (out_dir / "summary.json").read_text(encoding="utf-8")
    w1 = (out_dir / "windows.csv").read_text(encoding="utf-8")

    # Segunda ejecucion: mismas entradas
    write_report(cfg)
    j2 = (out_dir / "summary.json").read_text(encoding="utf-8")
    w2 = (out_dir / "windows.csv").read_text(encoding="utf-8")

    # Contenido identico (sin reloj, sin RNG — R9)
    assert j1 == j2, "summary.json no es determinista entre dos ejecuciones identicas"
    assert w1 == w2, "windows.csv no es determinista entre dos ejecuciones identicas"

    # Claves del JSON ordenadas en TODOS los niveles (R9)
    def _assert_keys_sorted(obj: object, path: str = "") -> None:
        """Recorre recursivamente el objeto JSON y verifica claves ordenadas."""
        if isinstance(obj, dict):
            keys = list(obj.keys())
            assert keys == sorted(keys), (
                f"Claves no ordenadas en '{path}': {keys} != {sorted(keys)}"
            )
            for k, v in obj.items():
                _assert_keys_sorted(v, path=f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _assert_keys_sorted(item, path=f"{path}[{i}]")

    _assert_keys_sorted(json.loads(j1))

    # Archivos existen
    assert (out_dir / "windows.csv").is_file()
    assert (out_dir / "calibration.csv").is_file()

    # Metricas presentes en el JSON
    data = json.loads(j1)
    assert "metrics" in data
    assert "model" in data["metrics"]
    assert "log_loss" in data["metrics"]["model"]


# ---------------------------------------------------------------------------
# R13 — test_low_data_en_summary_y_aviso_torneo
# ---------------------------------------------------------------------------


def test_low_data_en_summary_y_aviso_torneo(tmp_path):
    """R13: summary.json incluye low_data con attack/defense y flag low_data_en_torneo."""
    from src.backtest.report import write_report
    from src.backtest.walkforward import BacktestConfig

    # Dataset que genera low_data: AAA/BBB con muchos partidos, CCC con pocos
    from datetime import date, timedelta
    header = "match_id,date,home_code,away_code,home_goals,away_goals,neutral"
    rows = []
    cur = date(2020, 1, 1)
    mid = 1
    # AAA vs BBB: 50 partidos → no low_data con min_matches=5
    for i in range(50):
        rows.append(f"{mid},{cur.isoformat()},AAA,BBB,{i%3},{(i+1)%3},False")
        mid += 1
        cur += timedelta(days=7)
        rows.append(f"{mid},{cur.isoformat()},BBB,AAA,{i%3},{(i+1)%3},False")
        mid += 1
        cur += timedelta(days=7)

    # CCC: solo 2 partidos (< 5 = low_data)
    rows.append(f"{mid},{cur.isoformat()},CCC,AAA,1,0,False")
    mid += 1
    cur += timedelta(days=7)
    rows.append(f"{mid},{cur.isoformat()},BBB,CCC,0,1,False")
    mid += 1
    cur += timedelta(days=7)

    # Partidos de evaluacion con equipos conocidos
    rows.append(f"{mid},2024-01-10,AAA,BBB,1,0,False")
    mid += 1

    silver = tmp_path / "matches.csv"
    silver.write_text("\n".join([header] + rows) + "\n", encoding="utf-8")

    cfg = BacktestConfig(
        from_date="2024-01-01",
        to_date="2024-01-31",
        refit_every="month",
        silver_path=silver,
        out_dir=tmp_path / "out",
        min_matches=5,
    )

    summary = write_report(cfg)

    # low_data presente en summary
    assert "low_data" in summary
    low_data = summary["low_data"]
    assert "low_data_en_torneo" in low_data
    assert "teams" in low_data
    assert isinstance(low_data["low_data_en_torneo"], bool)

    # Si CCC esta en low_data, tiene attack y defense
    if low_data["teams"]:
        for team_info in low_data["teams"]:
            assert "code" in team_info
            # attack y defense pueden ser None si no se entreno, pero la clave existe
            assert "attack" in team_info
            assert "defense" in team_info

    # summary.json escrito en disco
    summary_path = tmp_path / "out" / "summary.json"
    assert summary_path.is_file()
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert "low_data" in data


# ---------------------------------------------------------------------------
# BacktestConfig — validacion dominio refit_every
# ---------------------------------------------------------------------------


def test_backtest_config_refit_every_invalido_raises_value_error():
    """BacktestConfig rechaza refit_every fuera de {'month','week'} en la capa de dominio."""
    from src.backtest.walkforward import BacktestConfig

    # Valores invalidos: cualquier cadena que no sea 'month' o 'week' debe lanzar ValueError
    for bad_value in ("biweekly", "daily", "quarter", "", "Month", "WEEK", "semana"):
        with pytest.raises(ValueError, match="refit_every"):
            BacktestConfig(refit_every=bad_value)

    # Valores validos no deben lanzar nada
    BacktestConfig(refit_every="month")
    BacktestConfig(refit_every="week")
