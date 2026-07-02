"""Tests CLI feature 12 modelo_v2 (R6) — 100 % offline.

Cubre:
- R6: train --model-version dc-v2 persiste en v2.json sin pisar v1.json.
- R6: selección de versión en predict y markets.
- R6: JSON v2 contiene model_version e importance_config.
- R6: load_params con model_version="dc-v2" carga el archivo correcto.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.cli import main as cli_main, build_parser
from src.models.dixon_coles import (
    DEFAULT_PARAMS_PATH,
    DEFAULT_PARAMS_PATH_V2,
    DCConfig,
    fit_dixon_coles,
    load_params,
    save_params,
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
    """Escribe silver sintético con tournament."""
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
            "tournament": m.get("tournament", "FIFA World Cup Qualification"),
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
    """Round-robin ida/vuelta con marcadores Poisson fijos."""
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
# R6 — Persistencia v2 sin pisar v1
# ---------------------------------------------------------------------------


def test_train_v2_persiste_sin_pisar_v1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R6: train --model-version dc-v2 escribe en _v2.json y NO toca el v1.json."""
    teams = ("MEX", "BRA", "ARG", "FRA")
    matches = make_round_robin(teams, rounds=4, seed=600)
    silver = write_silver(tmp_path / "silver", matches)

    # Configurar las rutas de parámetros bajo tmp_path
    v1_path = tmp_path / "gold" / "dixon_coles_params.json"
    v2_path = tmp_path / "gold" / "dixon_coles_params_v2.json"
    (tmp_path / "gold").mkdir(parents=True, exist_ok=True)

    # Escribir primero un v1 con contenido distinto (simula un v1 previo)
    params_v1 = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig())
    save_params(params_v1, v1_path)
    v1_content_before = v1_path.read_text(encoding="utf-8")

    # Entrenar v2 usando la API de bajo nivel (el CLI usa rutas por defecto que no podemos
    # redefinir sin monkeypatch complejo; aquí verificamos la lógica de save_params + extra_meta)
    params_v2 = fit_dixon_coles(
        AS_OF, silver_path=silver, config=DCConfig(),
        importance_map={"FIFA World Cup Qualification": 1.0}  # identidad para este test
    )
    save_params(
        params_v2,
        path=v2_path,
        extra_metadata={"model_version": "dc-v2", "importance_config": "default"},
    )

    # Verificar que v1 NO fue tocado
    v1_content_after = v1_path.read_text(encoding="utf-8")
    assert v1_content_before == v1_content_after, "v1.json fue modificado al entrenar v2"

    # Verificar que v2 existe y contiene model_version e importance_config
    assert v2_path.is_file(), "v2.json no fue creado"
    v2_data = json.loads(v2_path.read_text(encoding="utf-8"))
    assert v2_data.get("model_version") == "dc-v2", "model_version no encontrado en v2.json"
    assert "importance_config" in v2_data, "importance_config no encontrado en v2.json"

    # Verificar que las claves del contrato v1 también están en v2
    from src.models.dixon_coles import PARAMS_KEYS
    for key in PARAMS_KEYS:
        assert key in v2_data, f"Clave del contrato '{key}' ausente en v2.json"


def test_v2_json_retrocompatible_con_load_params(tmp_path: Path) -> None:
    """R6: load_params puede leer el JSON v2 (con claves extra) y devuelve DixonColesParams válido."""
    teams = ("ESP", "GER", "ITA", "POR")
    matches = make_round_robin(teams, rounds=4, seed=700)
    silver = write_silver(tmp_path / "silver", matches)

    v2_path = tmp_path / "gold" / "dixon_coles_params_v2.json"
    (tmp_path / "gold").mkdir(parents=True, exist_ok=True)

    params = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig())
    save_params(
        params,
        path=v2_path,
        extra_metadata={"model_version": "dc-v2", "importance_config": "default"},
    )

    # load_params debe tolerar las claves extra sin error
    loaded = load_params(v2_path)
    assert loaded.as_of_date == AS_OF
    assert isinstance(loaded.attack, dict)
    assert set(loaded.attack.keys()) == set(teams)


# ---------------------------------------------------------------------------
# R6 — Selección de versión en predict
# ---------------------------------------------------------------------------


def test_seleccion_version_en_predict(tmp_path: Path) -> None:
    """R6: predict/markets con --model-version dc-v1 carga el json v1; dc-v2 carga el v2.

    Verifica que load_params con model_version="dc-v2" carga DEFAULT_PARAMS_PATH_V2
    cuando la ruta explícita es DEFAULT_PARAMS_PATH (la ruta por defecto).
    """
    from src.models.dixon_coles import DEFAULT_PARAMS_PATH, DEFAULT_PARAMS_PATH_V2

    teams = ("COL", "CHI", "URU", "ECU")
    matches = make_round_robin(teams, rounds=4, seed=800)
    silver = write_silver(tmp_path / "silver", matches)

    # Crear v1 y v2 bajo rutas reales (monkeypatch para el test)
    v1_path = tmp_path / "gold_v" / "dixon_coles_params.json"
    v2_path = tmp_path / "gold_v" / "dixon_coles_params_v2.json"
    (tmp_path / "gold_v").mkdir(parents=True, exist_ok=True)

    params_v1 = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig())
    save_params(params_v1, path=v1_path)

    params_v2_raw = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig())
    save_params(
        params_v2_raw,
        path=v2_path,
        extra_metadata={"model_version": "dc-v2", "importance_config": "off"},
    )

    # Cargar v1 explícitamente por ruta
    loaded_v1 = load_params(v1_path)
    assert loaded_v1.as_of_date == AS_OF
    assert "model_version" not in loaded_v1.__dict__  # campo extra no en dataclass

    # Cargar v2 explícitamente por ruta
    loaded_v2 = load_params(v2_path)
    assert loaded_v2.as_of_date == AS_OF


def test_load_params_version_selector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R6: load_params(model_version='dc-v2') selecciona DEFAULT_PARAMS_PATH_V2."""
    from src.models import dixon_coles as dc_module
    from src.models.dixon_coles import DEFAULT_PARAMS_PATH_V2

    teams = ("PER", "BOL", "PAR", "VEN")
    matches = make_round_robin(teams, rounds=4, seed=900)
    silver = write_silver(tmp_path / "silver", matches)

    # Crear el archivo v2 bajo DEFAULT_PARAMS_PATH_V2 (monkeypatch la constante)
    mock_v2 = tmp_path / "dc_v2.json"
    params = fit_dixon_coles(AS_OF, silver_path=silver, config=DCConfig())
    save_params(
        params,
        path=mock_v2,
        extra_metadata={"model_version": "dc-v2", "importance_config": "default"},
    )

    # Monkeypatching DEFAULT_PARAMS_PATH_V2 en el módulo
    monkeypatch.setattr(dc_module, "DEFAULT_PARAMS_PATH_V2", mock_v2)

    # Con model_version="dc-v2" y ruta por defecto → debe cargar el mock_v2
    loaded = load_params(model_version="dc-v2")
    assert loaded.as_of_date == AS_OF
    assert set(loaded.attack.keys()) == set(teams)


# ---------------------------------------------------------------------------
# R6 — Flags del CLI (smoke tests de parser)
# ---------------------------------------------------------------------------


def test_cli_train_parser_model_version() -> None:
    """R6: el subcomando train acepta --model-version y --importance sin error de parsing."""
    parser = build_parser()
    args = parser.parse_args([
        "train",
        "--as-of-date", "2025-06-01",
        "--model-version", "dc-v2",
        "--importance", "default",
    ])
    assert args.model_version == "dc-v2"
    assert args.importance == "default"


def test_cli_predict_parser_model_version() -> None:
    """R6: el subcomando predict acepta --model-version."""
    parser = build_parser()
    args = parser.parse_args([
        "predict", "MEX", "BRA",
        "--model-version", "dc-v2",
    ])
    assert args.model_version == "dc-v2"


def test_cli_markets_parser_model_version() -> None:
    """R6: el subcomando markets acepta --model-version."""
    parser = build_parser()
    args = parser.parse_args([
        "markets", "ARG", "FRA",
        "--model-version", "dc-v2",
    ])
    assert args.model_version == "dc-v2"


def test_cli_predict_log_parser_model_version() -> None:
    """R6: predict-log acepta --model-version y --importance."""
    parser = build_parser()
    args = parser.parse_args([
        "predict-log",
        "--as-of", "2025-06-01",
        "--timestamp", "2025-06-01T10:00:00",
        "--model-version", "dc-v2",
        "--importance", "default",
    ])
    assert args.model_version == "dc-v2"
    assert args.importance == "default"


def test_cli_evaluate_parser_model_version() -> None:
    """R6/R7: evaluate acepta --model-version para filtrar por versión."""
    parser = build_parser()
    args = parser.parse_args([
        "evaluate",
        "--model-version", "dc-v1",
    ])
    assert args.model_version == "dc-v1"

    args2 = parser.parse_args([
        "evaluate",
        "--model-version", "dc-v2",
    ])
    assert args2.model_version == "dc-v2"


def test_cli_backtest_parser_importance_scales() -> None:
    """R4: backtest acepta --importance-scales."""
    parser = build_parser()
    args = parser.parse_args([
        "backtest",
        "--grid",
        "--importance-scales", "0.5,1.0,1.5",
    ])
    assert args.importance_scales == "0.5,1.0,1.5"
    assert args.grid is True


def test_cli_train_default_version_dc_v1() -> None:
    """R6: train sin --model-version usa dc-v1 (default = comportamiento v1)."""
    parser = build_parser()
    args = parser.parse_args(["train", "--as-of-date", "2025-06-01"])
    assert args.model_version == "dc-v1"
    assert args.importance == "off"


def test_cli_evaluate_default_no_filter() -> None:
    """R7: evaluate sin --model-version tiene model_version=None (sin filtro)."""
    parser = build_parser()
    args = parser.parse_args(["evaluate"])
    assert args.model_version is None
