"""tests/test_xg_proxy.py — Tests del proxy xG y la serie objetivo mezclada (Feature 15, R2–R5, R7).

Todos offline: fixtures en memoria, sin red real, sin reloj (as_of inyectado).

Mapeo trazabilidad:
- test_emparejamiento_silver_y_cobertura: R2
- test_partidos_sin_cobertura_marcados: R2
- test_proxy_xg_formula_oraculo: R3
- test_v0_equivale_v1: R4 (equivalencia tol 1e-9 — test crítico de no-regresión)
- test_serie_mezclada_solo_con_cobertura: R4
- test_anti_fuga_xg_no_predice_su_partido: R4
- test_backtest_sobre_cobertura_reproducible: R5
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.xg.proxy import (
    ALPHA_DEFAULT,
    BETA_DEFAULT,
    build_goal_target_series,
    build_xg_table,
    compute_xg_proxy,
    coverage_report,
)
from src.models.dixon_coles import (
    DCConfig,
    TrainingData,
    load_training_data,
    nll_weighted,
)

# ---------------------------------------------------------------------------
# Fixtures helper: silver mínimo en memoria
# ---------------------------------------------------------------------------


def _write_silver(tmp_path: Path, rows: list[dict]) -> Path:
    """Escribe un silver mínimo en tmp_path y devuelve la ruta."""
    silver = tmp_path / "silver" / "matches.csv"
    silver.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(silver, index=False)
    return silver


def _write_wiki_bronze(tmp_path: Path, entries: list[dict]) -> Path:
    """Escribe entradas de Wikipedia en bronze y devuelve el directorio."""
    wiki_dir = tmp_path / "bronze" / "wikipedia"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        slug = entry["slug"]
        safe_slug = slug.replace("/", "_").replace(" ", "_")
        doc = {
            "slug": slug,
            "match_id": entry.get("match_id"),
            "home_code": entry.get("home_code"),
            "away_code": entry.get("away_code"),
            "has_stats": len(entry.get("stats", [])) > 0,
            "stats": entry.get("stats", []),
        }
        (wiki_dir / f"{safe_slug}.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
    return wiki_dir


_SILVER_ROWS_BASE = [
    {
        "match_id": "m001",
        "date": "2024-06-01",
        "home_code": "MEX",
        "away_code": "POL",
        "home_goals": 2,
        "away_goals": 1,
        "neutral": False,
        "tournament": "FIFA World Cup",
    },
    {
        "match_id": "m002",
        "date": "2024-06-02",
        "home_code": "ARG",
        "away_code": "BRA",
        "home_goals": 3,
        "away_goals": 0,
        "neutral": True,
        "tournament": "FIFA World Cup",
    },
    {
        "match_id": "m003",
        "date": "2024-06-03",
        "home_code": "FRA",
        "away_code": "ESP",
        "home_goals": 1,
        "away_goals": 1,
        "neutral": False,
        "tournament": "FIFA World Cup",
    },
]

_WIKI_ENTRIES_PARTIAL = [
    {
        "slug": "Match_m001",
        "match_id": "m001",
        "home_code": "MEX",
        "away_code": "POL",
        "stats": [
            {"match_id": "m001", "team_code": "MEX", "shots": 15, "shots_on_target": 5, "possession": 55.0},
            {"match_id": "m001", "team_code": "POL", "shots": 10, "shots_on_target": 3, "possession": 45.0},
        ],
    },
    # m002 y m003 sin stats (cobertura parcial)
]


# ---------------------------------------------------------------------------
# R2: test_emparejamiento_silver_y_cobertura
# ---------------------------------------------------------------------------


def test_emparejamiento_silver_y_cobertura(tmp_path):
    """R2: normaliza stats al silver, empareja por (match_id, team_code), reporta cobertura %."""
    silver = _write_silver(tmp_path, _SILVER_ROWS_BASE)
    wiki_dir = _write_wiki_bronze(tmp_path, _WIKI_ENTRIES_PARTIAL)

    xg_table = build_xg_table(silver, wiki_dir)

    # 3 partidos × 2 equipos = 6 filas
    assert len(xg_table) == 6

    # m001 tiene cobertura para ambos equipos
    mex = xg_table[(xg_table["match_id"] == "m001") & (xg_table["team_code"] == "MEX")]
    pol = xg_table[(xg_table["match_id"] == "m001") & (xg_table["team_code"] == "POL")]
    assert len(mex) == 1
    assert len(pol) == 1
    assert bool(mex.iloc[0]["has_coverage"]) is True
    assert bool(pol.iloc[0]["has_coverage"]) is True

    # m002 y m003 sin cobertura
    m002 = xg_table[xg_table["match_id"] == "m002"]
    assert all(~m002["has_coverage"])

    # Cobertura parcial reportada correctamente
    report = coverage_report(xg_table)
    assert report["n_total"] == 6
    assert report["n_covered"] == 2  # MEX y POL de m001
    assert math.isclose(report["coverage_pct"], 100 * 2 / 6, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# R2: test_partidos_sin_cobertura_marcados
# ---------------------------------------------------------------------------


def test_partidos_sin_cobertura_marcados(tmp_path):
    """R2: partidos sin stats de Wikipedia quedan marcados con has_coverage=False."""
    silver = _write_silver(tmp_path, _SILVER_ROWS_BASE)
    # Sin ninguna entrada de Wikipedia
    wiki_dir = tmp_path / "bronze" / "wikipedia"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    xg_table = build_xg_table(silver, wiki_dir)

    assert len(xg_table) == 6
    assert not any(xg_table["has_coverage"])
    assert all(pd.isna(xg_table["xg_proxy"]))

    report = coverage_report(xg_table)
    assert report["n_covered"] == 0
    assert report["coverage_pct"] == 0.0


# ---------------------------------------------------------------------------
# R3: test_proxy_xg_formula_oraculo
# ---------------------------------------------------------------------------


def test_proxy_xg_formula_oraculo():
    """R3: xg_proxy = α·SoT + β·(shots − SoT), con los parámetros documentados."""
    # Oráculo: α=0.30, β=0.03
    # SoT=5, shots=15 → off_target=10
    # xg = 0.30*5 + 0.03*10 = 1.50 + 0.30 = 1.80
    xg = compute_xg_proxy(shots=15, shots_on_target=5)
    assert math.isclose(xg, 0.30 * 5 + 0.03 * 10, rel_tol=1e-9)

    # Oráculo 2: SoT=3, shots=10 → off_target=7
    # xg = 0.30*3 + 0.03*7 = 0.90 + 0.21 = 1.11
    xg2 = compute_xg_proxy(shots=10, shots_on_target=3)
    assert math.isclose(xg2, 0.30 * 3 + 0.03 * 7, rel_tol=1e-9)

    # Acotado a ≥ 0
    xg3 = compute_xg_proxy(shots=0, shots_on_target=0)
    assert xg3 is not None
    assert xg3 >= 0.0

    # Sin datos → None (sin cobertura)
    xg4 = compute_xg_proxy(shots=None, shots_on_target=5)
    assert xg4 is None

    xg5 = compute_xg_proxy(shots=10, shots_on_target=None)
    assert xg5 is None


def test_proxy_xg_formula_custom_alpha_beta():
    """R3: la fórmula es ajustable via alpha/beta (parámetros documentados, no hardcodeados)."""
    alpha = 0.25
    beta = 0.05
    shots, sot = 12, 4
    expected = alpha * sot + beta * (shots - sot)
    xg = compute_xg_proxy(shots=shots, shots_on_target=sot, alpha=alpha, beta=beta)
    assert math.isclose(xg, expected, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# R4: test_v0_equivale_v1 — test de equivalencia crítico
# ---------------------------------------------------------------------------


def test_v0_equivale_v1(tmp_path):
    """R4 (CRÍTICO): con v=0, la serie objetivo es idéntica a los goles reales (tol 1e-9).

    Este test verifica la no-regresión: load_training_data con xg_target_map=None
    produce los mismos arrays x/y que con v=0 (sin cobertura o mapa vacío).
    """
    silver = _write_silver(tmp_path, _SILVER_ROWS_BASE)
    wiki_dir = _write_wiki_bronze(tmp_path, _WIKI_ENTRIES_PARTIAL)

    config = DCConfig(from_date="2024-01-01", max_iter=5)
    as_of_date = "2025-01-01"

    # v1: load_training_data sin xg_target_map (goles reales)
    td_v1 = load_training_data(as_of_date, silver, config, xg_target_map=None)

    # Construir serie objetivo con v=0 → debe ser idéntica a los goles reales
    xg_table = build_xg_table(silver, wiki_dir)
    gt_series = build_goal_target_series(silver, xg_table, v=0.0)
    xg_map_v0 = {
        (str(row["match_id"]), str(row["team_code"])): float(row["goal_target"])
        for _, row in gt_series.iterrows()
    }

    # v0: load_training_data con xg_target_map donde goal_target = goles (v=0)
    td_v0 = load_training_data(as_of_date, silver, config, xg_target_map=xg_map_v0)

    # EQUIVALENCIA EXACTA tol 1e-9 (R4)
    assert np.allclose(td_v1.x, td_v0.x, atol=1e-9), (
        f"Arrays x difieren con v=0:\nv1={td_v1.x}\nv0={td_v0.x}"
    )
    assert np.allclose(td_v1.y, td_v0.y, atol=1e-9), (
        f"Arrays y difieren con v=0:\nv1={td_v1.y}\nv0={td_v0.y}"
    )
    assert np.allclose(td_v1.w, td_v0.w, atol=1e-9)


def test_v0_nll_identica_a_v1(tmp_path):
    """R4: la NLL con v=0 es idéntica a la NLL con goles reales (tol 1e-9)."""
    silver = _write_silver(tmp_path, _SILVER_ROWS_BASE)
    wiki_dir = _write_wiki_bronze(tmp_path, _WIKI_ENTRIES_PARTIAL)

    config = DCConfig(from_date="2024-01-01", max_iter=1)
    as_of_date = "2025-01-01"

    td_v1 = load_training_data(as_of_date, silver, config, xg_target_map=None)

    xg_table = build_xg_table(silver, wiki_dir)
    gt_series = build_goal_target_series(silver, xg_table, v=0.0)
    xg_map_v0 = {
        (str(row["match_id"]), str(row["team_code"])): float(row["goal_target"])
        for _, row in gt_series.iterrows()
    }
    td_v0 = load_training_data(as_of_date, silver, config, xg_target_map=xg_map_v0)

    n_teams = len(td_v1.teams)
    theta = np.zeros(3 + 2 * (n_teams - 1))
    theta[0] = 0.0  # mu
    theta[1] = 0.2  # gamma
    theta[2] = 0.0  # rho

    nll_v1 = nll_weighted(
        theta, td_v1.x, td_v1.y, td_v1.w, td_v1.h,
        td_v1.hi, td_v1.ai, n_teams, config.reg_lambda
    )
    nll_v0 = nll_weighted(
        theta, td_v0.x, td_v0.y, td_v0.w, td_v0.h,
        td_v0.hi, td_v0.ai, n_teams, config.reg_lambda
    )

    assert math.isclose(nll_v1, nll_v0, rel_tol=1e-9), (
        f"NLL v1={nll_v1} ≠ NLL v0={nll_v0}"
    )


# ---------------------------------------------------------------------------
# R4: test_serie_mezclada_solo_con_cobertura
# ---------------------------------------------------------------------------


def test_serie_mezclada_solo_con_cobertura(tmp_path):
    """R4: con v>0, la mezcla aplica SOLO donde hay cobertura; sin cobertura → goles reales."""
    silver = _write_silver(tmp_path, _SILVER_ROWS_BASE)
    wiki_dir = _write_wiki_bronze(tmp_path, _WIKI_ENTRIES_PARTIAL)

    xg_table = build_xg_table(silver, wiki_dir)
    v = 0.5

    gt_series = build_goal_target_series(silver, xg_table, v=v)

    # Verificar fila MEX (m001, con cobertura)
    mex_row = gt_series[(gt_series["match_id"] == "m001") & (gt_series["team_code"] == "MEX")]
    assert len(mex_row) == 1
    row = mex_row.iloc[0]
    assert bool(row["has_coverage"]) is True
    # Con cobertura: goal_target = (1-v)*goals + v*xg_proxy
    expected_gt = (1.0 - v) * float(row["goals"]) + v * float(row["xg_proxy"])
    assert math.isclose(float(row["goal_target"]), expected_gt, rel_tol=1e-9)

    # Verificar fila ARG (m002, sin cobertura)
    arg_row = gt_series[(gt_series["match_id"] == "m002") & (gt_series["team_code"] == "ARG")]
    assert len(arg_row) == 1
    row_arg = arg_row.iloc[0]
    assert row_arg["has_coverage"] is False or pd.isna(row_arg.get("xg_proxy"))
    # Sin cobertura: goal_target = goles reales (comportamiento v1)
    assert math.isclose(float(row_arg["goal_target"]), float(row_arg["goals"]), rel_tol=1e-9)


def test_serie_mezclada_v_invalido():
    """R4: v fuera de [0, 1] lanza ValueError."""
    import pandas as _pd
    silver_df = _pd.DataFrame({
        "match_id": ["m1"], "home_code": ["MEX"], "away_code": ["USA"],
        "home_goals": [2], "away_goals": [1], "neutral": [False], "date": ["2024-01-01"],
    })
    xg_table_df = _pd.DataFrame({
        "match_id": ["m1"], "team_code": ["MEX"],
        "xg_proxy": [1.5], "has_coverage": [True],
    })

    # Usamos un archivo temporal para poder llamar build_goal_target_series
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        silver_df.to_csv(f, index=False)
        fpath = Path(f.name)

    try:
        with pytest.raises(ValueError, match="v debe estar en"):
            build_goal_target_series(fpath, xg_table_df, v=1.5)
    finally:
        os.unlink(fpath)


# ---------------------------------------------------------------------------
# R4: test_anti_fuga_xg_no_predice_su_partido
# ---------------------------------------------------------------------------


def test_anti_fuga_xg_no_predice_su_partido(tmp_path):
    """R4: el xG de un partido NO informa la predicción de ESE partido (anti-fuga).

    La anti-fuga se preserva porque load_training_data aplica el filtro
    ``fecha < as_of_date`` ANTES de usar el xg_target_map. Por tanto, un partido
    con fecha >= as_of_date es excluido del entrenamiento aunque tenga xG.
    """
    # Silver con 3 partidos, el último en la fecha de corte
    rows = [
        {
            "match_id": "m001",
            "date": "2024-06-01",
            "home_code": "MEX",
            "away_code": "POL",
            "home_goals": 2,
            "away_goals": 1,
            "neutral": False,
            "tournament": "FIFA World Cup",
        },
        {
            "match_id": "m002",
            "date": "2024-06-02",
            "home_code": "ARG",
            "away_code": "BRA",
            "home_goals": 3,
            "away_goals": 0,
            "neutral": True,
            "tournament": "FIFA World Cup",
        },
        # Este partido está EN la fecha de corte → debe ser EXCLUIDO del training
        {
            "match_id": "m_cutoff",
            "date": "2025-01-01",
            "home_code": "FRA",
            "away_code": "ESP",
            "home_goals": 1,
            "away_goals": 1,
            "neutral": False,
            "tournament": "FIFA World Cup",
        },
    ]
    silver = _write_silver(tmp_path, rows)

    # xg_target_map incluye el partido de corte (para verificar que se excluye)
    xg_map = {
        ("m001", "MEX"): 2.1,
        ("m001", "POL"): 0.9,
        ("m002", "ARG"): 2.8,
        ("m002", "BRA"): 0.2,
        ("m_cutoff", "FRA"): 1.5,  # ← este NO debe entrar al training
        ("m_cutoff", "ESP"): 1.0,  # ← este NO debe entrar al training
    }

    config = DCConfig(from_date="2024-01-01")
    as_of_date = "2025-01-01"  # fecha de corte = fecha del partido m_cutoff

    td = load_training_data(as_of_date, silver, config, xg_target_map=xg_map)

    # Solo m001 y m002 deben estar en el training (m_cutoff está EN la fecha de corte)
    # El match_id m_cutoff tiene date "2025-01-01" que NO es < as_of_date "2025-01-01"
    assert td.x.size == 2  # solo 2 partidos en el training (m001, m002)
    assert td.y.size == 2

    # Los valores de x deben coincidir con los del mapa (m001 MEX y m002 ARG como home)
    # Orden: sorted por (date, match_id) → m001, m002
    assert math.isclose(td.x[0], 2.1, rel_tol=1e-9), f"x[0]={td.x[0]}, esperado 2.1"
    assert math.isclose(td.x[1], 2.8, rel_tol=1e-9), f"x[1]={td.x[1]}, esperado 2.8"


# ---------------------------------------------------------------------------
# R5: test_backtest_sobre_cobertura_reproducible
# ---------------------------------------------------------------------------


def test_backtest_sobre_cobertura_reproducible(tmp_path):
    """R5: con cobertura parcial, la serie objetivo mezclada es determinista y reproducible.

    Este test verifica que dos llamadas con los mismos parámetros producen la
    misma serie objetivo (determinismo, R7). La cobertura parcial se reporta.
    """
    silver = _write_silver(tmp_path, _SILVER_ROWS_BASE)
    wiki_dir = _write_wiki_bronze(tmp_path, _WIKI_ENTRIES_PARTIAL)

    xg_table1 = build_xg_table(silver, wiki_dir)
    xg_table2 = build_xg_table(silver, wiki_dir)

    gt1 = build_goal_target_series(silver, xg_table1, v=0.3)
    gt2 = build_goal_target_series(silver, xg_table2, v=0.3)

    # Determinismo: misma entrada → misma salida
    pd.testing.assert_frame_equal(
        gt1.sort_values(["match_id", "team_code"]).reset_index(drop=True),
        gt2.sort_values(["match_id", "team_code"]).reset_index(drop=True),
    )

    # Cobertura reportada correctamente (solo m001 tiene stats)
    report = coverage_report(xg_table1)
    assert report["n_covered"] == 2  # MEX y POL de m001
    assert report["n_total"] == 6   # 3 partidos × 2 equipos


def test_xg_table_sin_directorio_wikipedia(tmp_path):
    """R7: si no existe el directorio bronze de Wikipedia → xg_table sin cobertura (no aborta)."""
    silver = _write_silver(tmp_path, _SILVER_ROWS_BASE)
    wiki_dir = tmp_path / "bronze" / "wikipedia"
    # No creamos el directorio

    xg_table = build_xg_table(silver, wiki_dir)
    assert len(xg_table) == 6
    assert not any(xg_table["has_coverage"])


def test_coverage_report_sin_filas():
    """R2: coverage_report con DataFrame vacío devuelve coverage_pct=0.0."""
    empty_df = pd.DataFrame(columns=["match_id", "team_code", "xg_proxy", "has_coverage"])
    report = coverage_report(empty_df)
    assert report["coverage_pct"] == 0.0
    assert report["n_total"] == 0
    assert report["n_covered"] == 0
