"""Tests de importancia y equivalencia v1 del modelo Dixon-Coles (R1, R3) — feature 12.

100 % offline y deterministas: silver sintético en ``tmp_path``, cero red, cero reloj.
Cubre los requisitos R1 (equivalencia exacta con mapa identidad) y R3 (anti-fuga
preservada con importancia).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.models.dixon_coles import (
    DCConfig,
    TrainingData,
    fit_dixon_coles,
    load_training_data,
    decay_weights,
)
from src.models.importance import (
    IDENTITY_FACTORS,
    TIER_FACTORS,
    build_importance_map,
    classify_tournament,
    identity_importance_map,
    importance_factor,
)

AS_OF = "2025-06-01"

# ---------------------------------------------------------------------------
# Helpers compartidos
# ---------------------------------------------------------------------------

SILVER_COLUMNS: tuple[str, ...] = (
    "match_id", "date", "home_code", "away_code", "home_team", "away_team",
    "home_goals", "away_goals", "tournament", "neutral", "source",
    "home_corners", "away_corners", "home_cards", "away_cards",
    "home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target",
    "home_possession", "away_possession",
)

_STAT_COLUMNS = SILVER_COLUMNS[11:]


def write_silver_with_tournaments(
    dir_path: Path,
    matches: list[dict[str, Any]],
) -> Path:
    """Escribe silver sintético con columna ``tournament`` configurable por partido."""
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
    df = pd.DataFrame(rows, columns=list(SILVER_COLUMNS))
    path = dir_path / "matches.csv"
    df.to_csv(path, index=False)
    return path


def make_mixed_tournament_rows(
    teams: tuple[str, ...] = ("AAA", "BBB", "CCC", "DDD"),
    rounds: int = 3,
    seed: int = 42,
    start: str = "2024-01-01",
) -> list[dict[str, Any]]:
    """Calendario round-robin con torneos mixtos: mitad Friendly, mitad FIFA World Cup."""
    rng = np.random.default_rng(seed)
    base = date.fromisoformat(start)
    rows: list[dict[str, Any]] = []
    k = 0
    tournaments = ["Friendly", "FIFA World Cup Qualification", "FIFA World Cup"]
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
                    "tournament": tournaments[k % len(tournaments)],
                })
                k += 1
    return rows


# ---------------------------------------------------------------------------
# R1 — Equivalencia exacta con mapa identidad (test de no-regresión)
# ---------------------------------------------------------------------------


def test_default_identidad_equivale_v1(tmp_path: Path) -> None:
    """R1: ajuste con mapa identidad DEBE ser idéntico a v1 (sin importance_map).

    Verifica que todos los parámetros (mu, gamma, rho, attack, defense) coinciden
    con tolerancia 1e-9. Este es el test de no-regresión más crítico de la feature 12.
    """
    matches = make_mixed_tournament_rows()
    silver = write_silver_with_tournaments(tmp_path, matches)

    config = DCConfig()

    # Ajuste v1 (sin importance_map)
    params_v1 = fit_dixon_coles(AS_OF, silver_path=silver, config=config)

    # Ajuste con mapa IDENTIDAD explícito (todos los factores = 1.0)
    tournaments = [m["tournament"] for m in matches]
    id_map = identity_importance_map(tournaments)
    params_id = fit_dixon_coles(
        AS_OF, silver_path=silver, config=config, importance_map=id_map
    )

    tol = 1e-9
    assert abs(params_v1.mu - params_id.mu) < tol, (
        f"mu difiere: v1={params_v1.mu} vs identity={params_id.mu}"
    )
    assert abs(params_v1.home_advantage - params_id.home_advantage) < tol, (
        f"gamma difiere: v1={params_v1.home_advantage} vs identity={params_id.home_advantage}"
    )
    assert abs(params_v1.rho - params_id.rho) < tol, (
        f"rho difiere: v1={params_v1.rho} vs identity={params_id.rho}"
    )
    for code in params_v1.attack:
        assert abs(params_v1.attack[code] - params_id.attack[code]) < tol, (
            f"attack[{code}] difiere"
        )
        assert abs(params_v1.defense[code] - params_id.defense[code]) < tol, (
            f"defense[{code}] difiere"
        )

    # También verificar que n_matches es el mismo
    assert params_v1.n_matches == params_id.n_matches


def test_default_none_equivale_v1(tmp_path: Path) -> None:
    """R1: importance_map=None debe ser idéntico a v1 (sin importancia)."""
    matches = make_mixed_tournament_rows(seed=77)
    silver = write_silver_with_tournaments(tmp_path, matches)
    config = DCConfig()

    params_v1 = fit_dixon_coles(AS_OF, silver_path=silver, config=config)
    params_none = fit_dixon_coles(
        AS_OF, silver_path=silver, config=config, importance_map=None
    )

    tol = 1e-9
    assert abs(params_v1.mu - params_none.mu) < tol
    assert abs(params_v1.rho - params_none.rho) < tol


# ---------------------------------------------------------------------------
# R1 — test_w_es_decay_por_importance
# ---------------------------------------------------------------------------


def test_w_es_decay_por_importance(tmp_path: Path) -> None:
    """R1: w_i = exp(−ξ·Δaños) × importance(tournament_i) para cada partido."""
    # Crear silver con torneos conocidos
    matches = [
        {
            "date": "2024-01-01", "home_code": "AAA", "away_code": "BBB",
            "home_goals": 1, "away_goals": 0, "neutral": False,
            "tournament": "Friendly",  # factor 0.5
        },
        {
            "date": "2024-02-01", "home_code": "BBB", "away_code": "CCC",
            "home_goals": 2, "away_goals": 1, "neutral": False,
            "tournament": "FIFA World Cup",  # factor 1.5
        },
        {
            "date": "2024-03-01", "home_code": "CCC", "away_code": "AAA",
            "home_goals": 0, "away_goals": 2, "neutral": False,
            "tournament": "FIFA World Cup Qualification",  # factor 1.0
        },
        # Repetir para tener suficientes partidos (min_matches=5 default)
        {
            "date": "2024-04-01", "home_code": "AAA", "away_code": "CCC",
            "home_goals": 1, "away_goals": 1, "neutral": False,
            "tournament": "Friendly",
        },
        {
            "date": "2024-05-01", "home_code": "BBB", "away_code": "AAA",
            "home_goals": 2, "away_goals": 2, "neutral": False,
            "tournament": "FIFA World Cup",
        },
        {
            "date": "2024-06-01", "home_code": "CCC", "away_code": "BBB",
            "home_goals": 1, "away_goals": 0, "neutral": False,
            "tournament": "FIFA World Cup Qualification",
        },
    ]
    silver = write_silver_with_tournaments(tmp_path, matches)

    tournaments = [m["tournament"] for m in matches]
    imp_map = build_importance_map(tournaments, tier_factors=TIER_FACTORS)

    td = load_training_data(AS_OF, silver_path=silver, config=DCConfig(), importance_map=imp_map)
    td_v1 = load_training_data(AS_OF, silver_path=silver, config=DCConfig())

    # Los pesos v1 (solo decaimiento)
    decay = td_v1.w

    # Los factores de importancia esperados para cada partido (en orden de fecha)
    expected_factors = np.array([
        imp_map.get("Friendly", 1.0),                     # 2024-01-01
        imp_map.get("FIFA World Cup", 1.0),                # 2024-02-01
        imp_map.get("FIFA World Cup Qualification", 1.0),  # 2024-03-01
        imp_map.get("Friendly", 1.0),                      # 2024-04-01
        imp_map.get("FIFA World Cup", 1.0),                # 2024-05-01
        imp_map.get("FIFA World Cup Qualification", 1.0),  # 2024-06-01
    ])

    expected_w = decay * expected_factors
    np.testing.assert_allclose(td.w, expected_w, rtol=1e-9, atol=1e-12)


# ---------------------------------------------------------------------------
# R3 — Anti-fuga preservada con importancia
# ---------------------------------------------------------------------------


def test_anti_fuga_con_importancia(tmp_path: Path) -> None:
    """R3: mutar partidos POSTERIORES a as_of_date no cambia el ajuste con importancia.

    Escribe un silver con partidos antes Y después de as_of_date.
    Los posteriores se mutan radicalmente (goles ×100, torneo cambiado).
    El ajuste con importance_map debe ser IDÉNTICO al del silver original (tol 1e-9).
    """
    base_matches = make_mixed_tournament_rows(seed=99)
    as_of = "2025-03-01"

    # Silver original: partidos mezclados (algunos antes de as_of, algunos después)
    (tmp_path / "orig").mkdir(parents=True, exist_ok=True)
    silver_orig = write_silver_with_tournaments(tmp_path / "orig", base_matches)

    # Silver mutado: los partidos DESPUÉS de as_of tienen goles ×100 y torneo cambiado
    mutated = []
    for m in base_matches:
        if m["date"] >= as_of:
            mutated.append({**m, "home_goals": 100, "away_goals": 100, "tournament": "INVALID"})
        else:
            mutated.append(m)
    (tmp_path / "mut").mkdir(parents=True, exist_ok=True)
    silver_mut = write_silver_with_tournaments(tmp_path / "mut", mutated)

    config = DCConfig(from_date="2024-01-01")

    # Mapa de importancia desde los torneos del silver original (partidos filtrados)
    tournaments_before = [m["tournament"] for m in base_matches if m["date"] < as_of]
    imp_map = build_importance_map(
        tournaments_before + ["Friendly", "FIFA World Cup", "FIFA World Cup Qualification"],
        tier_factors=TIER_FACTORS,
    )

    params_orig = fit_dixon_coles(as_of, silver_path=silver_orig, config=config, importance_map=imp_map)
    params_mut = fit_dixon_coles(as_of, silver_path=silver_mut, config=config, importance_map=imp_map)

    tol = 1e-9
    assert abs(params_orig.mu - params_mut.mu) < tol, (
        f"mu difiere pese a anti-fuga: {params_orig.mu} vs {params_mut.mu}"
    )
    assert abs(params_orig.rho - params_mut.rho) < tol
    assert params_orig.n_matches == params_mut.n_matches, (
        "n_matches difiere: la mutación de partidos posteriores se filtró incorrectamente"
    )
    for code in params_orig.attack:
        assert abs(params_orig.attack[code] - params_mut.attack[code]) < tol, (
            f"attack[{code}] difiere pese a anti-fuga"
        )
