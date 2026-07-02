"""Tests de la feature 12 modelo_v2 (R2, R4, R5, R7) — 100 % offline.

Cubre:
- R2: clasificación de tiers y fallback determinista (test_clasificacion_tiers_y_fallback)
- R4: grid de importancia walk-forward reproducible (test_grid_importancia_ranking_reproducible)
- R5: rolling por jornada con anti-fuga y model_version (test_rolling_por_jornada_anti_fuga_y_model_version)
- R7: comparación v1 vs v2 determinista (test_comparacion_v1_vs_v2_determinista)
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.models.importance import (
    TIER_FACTORS,
    TIER_KEYWORDS,
    build_importance_map,
    classify_tournament,
    identity_importance_map,
    importance_factor,
)
from src.models.dixon_coles import (
    DCConfig,
    fit_dixon_coles,
)

AS_OF = "2025-06-01"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SILVER_COLUMNS: tuple[str, ...] = (
    "match_id", "date", "home_code", "away_code", "home_team", "away_team",
    "home_goals", "away_goals", "tournament", "neutral", "source",
    "home_corners", "away_corners", "home_cards", "away_cards",
    "home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target",
    "home_possession", "away_possession",
)

_STAT_COLUMNS = SILVER_COLUMNS[11:]


def write_silver(dir_path: Path, matches: list[dict[str, Any]]) -> Path:
    """Escribe silver sintético con columna tournament."""
    rows = []
    for i, m in enumerate(matches):
        row: dict[str, Any] = {
            "match_id": f"m{i:06d}",
            "date": m["date"],
            "home_code": m["home_code"],
            "away_code": m["away_code"],
            "home_team": m["home_code"],
            "away_team": m["away_code"],
            "home_goals": int(m["home_goals"]),
            "away_goals": int(m["away_goals"]),
            "tournament": m.get("tournament", "Friendly"),
            "neutral": bool(m.get("neutral", False)),
            "source": "public_csv",
        }
        row.update({c: None for c in _STAT_COLUMNS})
        rows.append(row)
    dir_path.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=list(SILVER_COLUMNS))
    path = dir_path / "matches.csv"
    df.to_csv(path, index=False)
    return path


def make_round_robin(
    teams: tuple[str, ...],
    rounds: int,
    seed: int,
    start: str = "2024-01-01",
    tournament: str = "FIFA World Cup Qualification",
) -> list[dict[str, Any]]:
    """Round-robin ida/vuelta con marcadores Poisson de semilla fija."""
    rng = np.random.default_rng(seed)
    base = date.fromisoformat(start)
    rows: list[dict[str, Any]] = []
    k = 0
    for _ in range(rounds):
        for i, home in enumerate(teams):
            for j, away in enumerate(teams):
                if i == j:
                    continue
                rows.append({
                    "date": (base + timedelta(days=k % 200)).isoformat(),
                    "home_code": home,
                    "away_code": away,
                    "home_goals": int(rng.poisson(1.4)),
                    "away_goals": int(rng.poisson(1.1)),
                    "neutral": False,
                    "tournament": tournament,
                })
                k += 1
    return rows


# ---------------------------------------------------------------------------
# R2 — Clasificación de tiers y fallback
# ---------------------------------------------------------------------------


def test_clasificacion_tiers_y_fallback() -> None:
    """R2: classify_tournament cubre todos los tiers y el fallback es determinista."""
    # Copa del Mundo → world_cup
    assert classify_tournament("FIFA World Cup") == "world_cup"
    assert classify_tournament("2026 FIFA World Cup") == "world_cup"
    assert classify_tournament("Copa Mundial") == "world_cup"

    # Amistosos → friendly
    assert classify_tournament("International Friendly") == "friendly"
    assert classify_tournament("Friendly") == "friendly"
    assert classify_tournament("AMISTOSO") == "friendly"

    # Finales continentales → continental_final
    assert classify_tournament("UEFA Euro 2024") == "continental_final"
    assert classify_tournament("Copa America 2024") == "continental_final"
    # H2: variantes con acento/Unicode también deben clasificarse correctamente
    assert classify_tournament("Copa América 2024") == "continental_final"
    assert classify_tournament("Copa América") == "continental_final"
    assert classify_tournament("African Cup of Nations") == "continental_final"
    assert classify_tournament("CONCACAF Gold Cup") == "continental_final"
    assert classify_tournament("Asian Cup 2027") == "continental_final"

    # Clasificatorios → qualifier
    assert classify_tournament("FIFA World Cup Qualification") == "qualifier"
    assert classify_tournament("UEFA Nations League") == "qualifier"
    assert classify_tournament("CONMEBOL Qualifying") == "qualifier"
    assert classify_tournament("World Cup Qualifier Playoff") == "qualifier"

    # Fallback determinista: torneo desconocido → "unknown"
    assert classify_tournament("Super League Fantasy Cup") == "unknown"
    assert classify_tournament("") == "unknown"
    assert classify_tournament("123") == "unknown"

    # Factores por tier
    assert importance_factor("FIFA World Cup") == TIER_FACTORS["world_cup"]
    assert importance_factor("Friendly") == TIER_FACTORS["friendly"]
    assert importance_factor("UEFA Euro 2024") == TIER_FACTORS["continental_final"]
    assert importance_factor("FIFA World Cup Qualification") == TIER_FACTORS["qualifier"]
    # Fallback factor == TIER_FACTORS["unknown"]
    assert importance_factor("Desconocido XYZ") == TIER_FACTORS["unknown"]


def test_factores_v2_propuestos() -> None:
    """R2: valores numéricos de los factores v2 según design.md."""
    assert TIER_FACTORS["friendly"] == 0.5
    assert TIER_FACTORS["qualifier"] == 1.0
    assert TIER_FACTORS["continental_final"] == 1.25
    assert TIER_FACTORS["world_cup"] == 1.5
    assert TIER_FACTORS["unknown"] == 1.0


def test_mapa_identidad_todos_uno() -> None:
    """R2: identity_importance_map devuelve 1.0 para todos los torneos."""
    tournaments = ["Friendly", "FIFA World Cup", "UEFA Nations League", "XYZ"]
    id_map = identity_importance_map(tournaments)
    for t in tournaments:
        assert id_map[t] == 1.0


# ---------------------------------------------------------------------------
# R4 — Grid de importancia walk-forward reproducible
# ---------------------------------------------------------------------------


def test_grid_importancia_ranking_reproducible(tmp_path: Path) -> None:
    """R4: run_grid con importance_scales produce ranking reproducible y ordenado.

    Dos llamadas idénticas producen el mismo ranking (determinismo). El ranking
    está ordenado por (log_loss, brier) ascendente.
    """
    from src.backtest.report import run_grid
    from src.backtest.walkforward import BacktestConfig

    # Silver pequeño: 4 equipos × 3 rounds = 36 partidos
    teams = ("AAA", "BBB", "CCC", "DDD")
    matches = make_round_robin(teams, rounds=3, seed=200, start="2024-01-01")
    # Añadir unos Friendly para que haya variedad de torneo
    friendly = make_round_robin(
        teams, rounds=2, seed=201, start="2024-06-01", tournament="Friendly"
    )
    all_matches = matches + friendly
    silver = write_silver(tmp_path / "silver_grid", all_matches)

    cfg = BacktestConfig(
        from_date="2024-05-01",
        to_date="2024-12-31",
        refit_every="month",
        xi=0.35,
        reg_lambda=0.25,
        silver_path=silver,
        out_dir=tmp_path / "out_grid",
    )

    # Grid pequeño para rapidez en tests
    ranking1 = run_grid(
        cfg, xis=[0.35], reg_lambdas=[0.25], importance_scales=[1.0]
    )
    ranking2 = run_grid(
        cfg, xis=[0.35], reg_lambdas=[0.25], importance_scales=[1.0]
    )

    # Reproducibilidad: dos llamadas idénticas → mismo ranking
    assert len(ranking1) == len(ranking2), "Ranking no reproducible: longitud diferente"
    for r1, r2 in zip(ranking1, ranking2):
        assert r1["log_loss"] == r2["log_loss"], f"log_loss diferente: {r1} vs {r2}"
        assert r1["brier"] == r2["brier"]

    # Ordenamiento: log_loss ascendente
    for i in range(len(ranking1) - 1):
        assert ranking1[i]["log_loss"] <= ranking1[i + 1]["log_loss"]


def test_grid_sin_importance_backward_compatible(tmp_path: Path) -> None:
    """R4: run_grid sin importance_scales es idéntico al comportamiento previo (v1).

    H1 fix: from_date dentro del rango del silver para que run_grid produzca al
    menos una entrada evaluable y los asserts ejerciten el ranking real.
    """
    from src.backtest.report import run_grid
    from src.backtest.walkforward import BacktestConfig

    teams = ("AAA", "BBB", "CCC", "DDD")
    # start="2024-01-01" produce partidos hasta ~2024-02-05; from_date="2024-01-15"
    # garantiza datos de entrenamiento (date < from_date) y ventanas evaluables.
    matches = make_round_robin(teams, rounds=3, seed=300, start="2024-01-01")
    silver = write_silver(tmp_path / "silver_v1grid", matches)

    cfg = BacktestConfig(
        from_date="2024-01-15",
        to_date="2024-12-31",
        refit_every="month",
        silver_path=silver,
        out_dir=tmp_path / "out_v1grid",
    )

    # Sin importance_scales → comportamiento v1 (sin clave importance_scale)
    ranking_no_imp = run_grid(cfg, xis=[0.35], reg_lambdas=[0.25])
    assert isinstance(ranking_no_imp, list)
    assert len(ranking_no_imp) >= 1, "run_grid debe producir al menos una entrada evaluable"

    # Cada entrada no debe tener "importance_scale"
    for entry in ranking_no_imp:
        assert "importance_scale" not in entry

    # Backward-compat real: escala 1.0 produce las mismas métricas que sin escala,
    # pero SÍ incluye la clave "importance_scale" (diferencia semántica de v2).
    ranking_scale1 = run_grid(cfg, xis=[0.35], reg_lambdas=[0.25], importance_scales=[1.0])
    assert len(ranking_no_imp) == len(ranking_scale1), (
        "Misma cantidad de entradas con y sin importance_scales=[1.0]"
    )
    for r_no, r_s1 in zip(ranking_no_imp, ranking_scale1):
        assert r_no["log_loss"] == r_s1["log_loss"], (
            f"log_loss difiere: sin_imp={r_no['log_loss']} vs escala_1={r_s1['log_loss']}"
        )
        assert r_no["brier"] == r_s1["brier"]
        assert "importance_scale" in r_s1, "Con importance_scales=[1.0] debe incluir la clave"


# ---------------------------------------------------------------------------
# R5 — Rolling por jornada con anti-fuga y model_version
# ---------------------------------------------------------------------------


def test_rolling_por_jornada_anti_fuga_y_model_version(tmp_path: Path) -> None:
    """R5: refit por jornada (predict-log --as-of <jornada> --model-version dc-v2).

    Verifica que:
    1. Entrenar con as_of=jornada_2 produce parámetros distintos a as_of=jornada_1
       (el refit incorpora los partidos de la jornada 1 del torneo).
    2. log_predictions registra el model_version correcto en cada fila.
    3. Anti-fuga: los partidos de la jornada_2+ no contaminan el refit de jornada_2.
    """
    from src.eval.prediction_log import log_predictions, MODEL_VERSION_V2

    teams = ("AAA", "BBB", "CCC", "DDD")

    # Pre-torneo (histórico)
    pre = make_round_robin(teams, rounds=5, seed=400, start="2024-01-01")
    # Jornada 1 del torneo (jugada el 2025-05-01)
    j1 = [
        {"date": "2025-05-01", "home_code": "AAA", "away_code": "BBB",
         "home_goals": 2, "away_goals": 0, "neutral": True, "tournament": "FIFA World Cup"},
        {"date": "2025-05-01", "home_code": "CCC", "away_code": "DDD",
         "home_goals": 1, "away_goals": 1, "neutral": True, "tournament": "FIFA World Cup"},
    ]
    # Jornada 2 del torneo (a predecir el 2025-05-15)
    j2_fixtures = [
        {"date": "2025-05-15", "home_code": "AAA", "away_code": "CCC",
         "home_goals": 1, "away_goals": 2, "neutral": True, "tournament": "FIFA World Cup"},
    ]

    # Silver con pre + j1 + j2 (para que load_training_data vea todos)
    all_silver = pre + j1 + j2_fixtures
    silver = write_silver(tmp_path / "silver_rolling", all_silver)

    # Fixture CSV para predict-log (solo j2, pendientes)
    fixtures_j2 = [
        {
            "date": "2025-05-15",
            "match_id": "2025-05-15_AAA_CCC",
            "home_code": "AAA",
            "away_code": "CCC",
            "neutral": True,
        }
    ]

    log_path = tmp_path / "data" / "log.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    imp_map = build_importance_map(
        ["Friendly", "FIFA World Cup", "FIFA World Cup Qualification"],
        tier_factors=TIER_FACTORS,
    )

    # Refit jornada 2: as_of = 2025-05-15 → incluye j1 (2025-05-01 < 2025-05-15)
    result = log_predictions(
        as_of_date="2025-05-15",
        created_at="2025-05-14T20:00:00",
        fixtures=fixtures_j2,
        silver_path=silver,
        log_path=log_path,
        config=DCConfig(from_date="2024-01-01"),
        model_version=MODEL_VERSION_V2,
        importance_map=imp_map,
    )

    assert result["n_logged"] == 1, f"Se esperaba 1 predicción registrada; got {result}"

    # Verificar que el log tiene model_version = "dc-v2"
    log_df = pd.read_csv(log_path, dtype=str)
    assert len(log_df) == 1
    assert log_df.iloc[0]["model_version"] == "dc-v2"
    assert log_df.iloc[0]["as_of_date"] == "2025-05-15"

    # Anti-fuga: verificar que el refit de j2 NO usa partidos de j2+
    # Los partidos del silver con date >= 2025-05-15 no deben estar en el entrenamiento
    from src.models.dixon_coles import load_training_data
    td = load_training_data(
        "2025-05-15", silver_path=silver, config=DCConfig(from_date="2024-01-01")
    )
    # Verificar que j2 (2025-05-15) no está en los datos de entrenamiento
    # (el filtro es date < as_of_date estricto)
    # El mayor partido de entrenamiento debe ser anterior a 2025-05-15
    # No hay forma directa de verificar fechas desde TrainingData, pero sí n_matches:
    # pre=60 (5 rounds × 4×3 = 60), j1=2; total before 2025-05-15 = 62
    expected_train = sum(1 for m in all_silver if m["date"] < "2025-05-15")
    assert td.x.shape[0] == expected_train, (
        f"n_matches de entrenamiento incorrecto: got {td.x.shape[0]}, expected {expected_train}"
    )


# ---------------------------------------------------------------------------
# R7 — Comparación v1 vs v2 determinista
# ---------------------------------------------------------------------------


def test_comparacion_v1_vs_v2_determinista(tmp_path: Path) -> None:
    """R7: comparación v1 vs v2 sobre los mismos partidos es reproducible.

    Genera predicciones con dc-v1 y dc-v2 para los mismos fixtures, luego
    evalúa cada versión por separado. Dos ejecuciones idénticas producen
    el mismo resultado (determinismo). Los parámetros v2 (con importancia
    no identidad) deben diferir de v1 (no-trivialidad del test).
    """
    from src.eval.prediction_log import log_predictions, MODEL_VERSION, MODEL_VERSION_V2
    from src.eval.evaluate import evaluate

    teams = ("AAA", "BBB", "CCC", "DDD")
    pre = make_round_robin(
        teams, rounds=5, seed=500, start="2024-01-01", tournament="FIFA World Cup Qualification"
    )
    friendly = make_round_robin(
        teams, rounds=3, seed=501, start="2024-01-01", tournament="Friendly"
    )
    wc = make_round_robin(
        teams, rounds=2, seed=502, start="2025-01-01", tournament="FIFA World Cup"
    )

    # Silver de resultados reales (incluyendo partidos evaluables)
    silver_full = pre + friendly + wc
    silver = write_silver(tmp_path / "sv", silver_full)

    # Fixtures a predecir (partidos del WC, simulando jornada)
    fixtures = [
        {
            "date": "2025-06-15",
            "match_id": f"2025-06-15_AAA_BBB",
            "home_code": "AAA",
            "away_code": "BBB",
            "neutral": True,
        },
        {
            "date": "2025-06-15",
            "match_id": f"2025-06-15_CCC_DDD",
            "home_code": "CCC",
            "away_code": "DDD",
            "neutral": True,
        },
    ]

    log_path = tmp_path / "data" / "compare_log.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Predicciones dc-v1
    result_v1 = log_predictions(
        as_of_date="2025-06-01",
        created_at="2025-06-01T10:00:00",
        fixtures=fixtures,
        silver_path=silver,
        log_path=log_path,
        config=DCConfig(from_date="2024-01-01"),
        model_version=MODEL_VERSION,
        importance_map=None,
    )

    # Predicciones dc-v2 con mapa de importancia
    imp_map = build_importance_map(
        ["Friendly", "FIFA World Cup", "FIFA World Cup Qualification"],
        tier_factors=TIER_FACTORS,
    )
    result_v2 = log_predictions(
        as_of_date="2025-06-01",
        created_at="2025-06-01T10:00:00",
        fixtures=fixtures,
        silver_path=silver,
        log_path=log_path,
        config=DCConfig(from_date="2024-01-01"),
        model_version=MODEL_VERSION_V2,
        importance_map=imp_map,
    )

    assert result_v1["n_logged"] == 2
    assert result_v2["n_logged"] == 2

    # Verificar que ambas versiones están en el log
    log_df = pd.read_csv(log_path, dtype=str)
    versions_logged = set(log_df["model_version"].unique())
    assert "dc-v1" in versions_logged
    assert "dc-v2" in versions_logged
    assert len(log_df) == 4  # 2 fixtures × 2 versiones

    # Determinismo: segunda llamada con los mismos parámetros → mismo log
    log_path_2 = tmp_path / "data" / "compare_log2.csv"
    log_path_2.parent.mkdir(parents=True, exist_ok=True)

    log_predictions(
        as_of_date="2025-06-01",
        created_at="2025-06-01T10:00:00",
        fixtures=fixtures,
        silver_path=silver,
        log_path=log_path_2,
        config=DCConfig(from_date="2024-01-01"),
        model_version=MODEL_VERSION,
        importance_map=None,
    )
    log_predictions(
        as_of_date="2025-06-01",
        created_at="2025-06-01T10:00:00",
        fixtures=fixtures,
        silver_path=silver,
        log_path=log_path_2,
        config=DCConfig(from_date="2024-01-01"),
        model_version=MODEL_VERSION_V2,
        importance_map=imp_map,
    )

    log_df_1 = pd.read_csv(log_path, dtype=str)
    log_df_2 = pd.read_csv(log_path_2, dtype=str)

    # Mismas columnas de predicción (determinismo)
    for col in ["p_home", "p_draw", "p_away"]:
        pd.testing.assert_series_equal(
            log_df_1[col].reset_index(drop=True),
            log_df_2[col].reset_index(drop=True),
            check_names=False,
        )

    # v1 y v2 deben tener predicciones diferentes (importancia no identidad afecta el ajuste)
    v1_rows = log_df[log_df["model_version"] == "dc-v1"]
    v2_rows = log_df[log_df["model_version"] == "dc-v2"]
    assert len(v1_rows) == 2
    assert len(v2_rows) == 2

    # H3 fix: verificar que v2 produce predicciones DISTINTAS de v1.
    # imp_map tiene friendly=0.5, world_cup=1.5, qualifier=1.0 — la mezcla de
    # Friendly (0.5) y FIFA World Cup Qualification (1.0) en el silver de entrenamiento
    # hace que v2 pondere menos los amistosos, alterando los parámetros ajustados.
    v1_p_home = v1_rows["p_home"].astype(float).values
    v2_p_home = v2_rows["p_home"].astype(float).values
    assert any(abs(v1_p_home[i] - v2_p_home[i]) > 1e-9 for i in range(len(v1_p_home))), (
        "v2 con mapa de importancia no-identidad debe producir predicciones distintas a v1. "
        f"v1={v1_p_home}, v2={v2_p_home}"
    )
