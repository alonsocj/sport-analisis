"""Orquestación bronze → silver → gold (R7, R19–R21).

``build_all(as_of_date, ...)`` construye silver, calcula el Elo global y las medias
móviles, y escribe los tres CSVs de forma determinista: ``data/silver/matches.csv``,
``data/gold/elo_history.csv`` y ``data/gold/team_features.csv`` (exactamente una fila
por cada una de las 48 selecciones, R20). ``as_of_date`` es SIEMPRE inyectada
(``YYYY-MM-DD``; nunca ``now()`` implícito) → reproducible y anti-leakage (R21).

CLI opcional (sin red): ``python -m src.features.build --as-of-date YYYY-MM-DD``.
Procesamiento 100% offline; no usa ``API_FOOTBALL_KEY``.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from ..ingestion.teams import all_teams
from .elo import EloParams, ratings_as_of, run_elo
from .rolling import ROLLING_WINDOW, compute_rolling_features
from .silver import build_silver, write_silver

DEFAULT_BRONZE_DIR = Path("data/bronze")
DEFAULT_SILVER_DIR = Path("data/silver")
DEFAULT_GOLD_DIR = Path("data/gold")

# Contrato de ``data/gold/team_features.csv``: columnas en este ORDEN exacto (R20).
TEAM_FEATURES_COLUMNS: tuple[str, ...] = (
    "code",
    "as_of_date",
    "matches_count",
    "gf_ma15",
    "ga_ma15",
    "corners_for_ma15",
    "corners_against_ma15",
    "cards_ma15",
    "shots_ma15",
    "shots_on_target_ma15",
    "possession_ma15",
    "elo",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_as_of_date(as_of_date: str) -> None:
    """``as_of_date`` mal formada → ``ValueError`` con el formato esperado (R21)."""
    if not isinstance(as_of_date, str) or not _DATE_RE.match(as_of_date):
        raise ValueError(
            f"as_of_date inválida: {as_of_date!r}; formato esperado YYYY-MM-DD"
        )
    try:
        date.fromisoformat(as_of_date)
    except ValueError as exc:
        raise ValueError(
            f"as_of_date inválida: {as_of_date!r}; formato esperado YYYY-MM-DD"
        ) from exc


def build_all(
    as_of_date: str,
    bronze_dir: Path | str = DEFAULT_BRONZE_DIR,
    silver_dir: Path | str = DEFAULT_SILVER_DIR,
    gold_dir: Path | str = DEFAULT_GOLD_DIR,
    elo_params: EloParams | None = None,
    window: int = ROLLING_WINDOW,
) -> dict[str, Any]:
    """Construye silver y gold y escribe los tres CSVs de forma determinista (R21).

    - Silver: ``matches.csv`` con el contrato exacto (R7).
    - Elo global sobre TODOS los partidos de silver, incluidos los de equipos fuera de
      las 48 → ``elo_history.csv`` (R19).
    - ``team_features.csv``: exactamente una fila por cada una de las 48 selecciones de
      ``teams.py`` (aunque no tengan partidos previos), ``elo`` vigente a ``as_of_date``
      con partidos estrictamente anteriores (R20).

    Devuelve un resumen: ``n_matches_silver``, ``n_teams_gold`` y rutas escritas.
    """
    _validate_as_of_date(as_of_date)
    params = elo_params or EloParams()

    silver = build_silver(bronze_dir)
    matches_path = write_silver(silver, silver_dir)

    gold_dir = Path(gold_dir)
    gold_dir.mkdir(parents=True, exist_ok=True)

    _final_ratings, history = run_elo(silver, params)  # R19: alcance global
    elo_history_path = gold_dir / "elo_history.csv"
    history.to_csv(elo_history_path, index=False)

    codes = sorted(team.code for team in all_teams())  # R20: las 48 selecciones
    features = compute_rolling_features(silver, codes, as_of_date, window)
    current = ratings_as_of(history, as_of_date)
    features["as_of_date"] = as_of_date
    features["elo"] = [current.get(code, params.initial) for code in features["code"]]
    features = features[list(TEAM_FEATURES_COLUMNS)]
    team_features_path = gold_dir / "team_features.csv"
    features.to_csv(team_features_path, index=False)

    return {
        "n_matches_silver": int(len(silver)),
        "n_teams_gold": int(len(features)),
        "paths": {
            "matches": str(matches_path),
            "elo_history": str(elo_history_path),
            "team_features": str(team_features_path),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """CLI sin red: construye silver y gold para una ``as_of_date`` inyectada (R21)."""
    parser = argparse.ArgumentParser(
        description="Construye silver y gold (offline, sin red) — feature_store R21."
    )
    parser.add_argument(
        "--as-of-date",
        required=True,
        help="Fecha YYYY-MM-DD inyectada (anti-leakage; nunca now() implícito)",
    )
    parser.add_argument("--bronze-dir", default=str(DEFAULT_BRONZE_DIR))
    parser.add_argument("--silver-dir", default=str(DEFAULT_SILVER_DIR))
    parser.add_argument("--gold-dir", default=str(DEFAULT_GOLD_DIR))
    args = parser.parse_args(argv)
    summary = build_all(
        args.as_of_date,
        bronze_dir=Path(args.bronze_dir),
        silver_dir=Path(args.silver_dir),
        gold_dir=Path(args.gold_dir),
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
