"""src/features/lineup_strength.py — Fuerza de alineación por (partido, equipo) (Feature 28, R3).

Deriva desde ``data/bronze/lineups/*.json`` una tabla con la calidad del XI titular:
``xi_rating`` (media de season_rating de titulares) y un split ``att_rating``/``def_rating``
por posición. La consume el modelo v3 (F29) como ajuste a prediction-time.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_BRONZE_DIR = Path("data") / "bronze"
DEFAULT_GOLD_DIR = Path("data") / "gold"

LINEUP_STRENGTH_COLUMNS = (
    "date", "team_code", "xi_rating", "att_rating", "def_rating",
    "n_starters", "lineup_type",
)

# usualPlayingPositionId de fotmob → pesos (att, def). Esquema verificado en datos reales
# WC2026 (2026-07-04): 0=GK, 1=DEF, 2=MID, 3=ATT (E.Martínez GK=0; Kane/Mbappé/Lautaro=3;
# L.Martínez CB=1). MID reparte 0.5/0.5. Desconocido → 0.5/0.5.
_POS_WEIGHTS: dict[int, tuple[float, float]] = {
    0: (0.0, 1.0),  # GK → defensa
    1: (0.0, 1.0),  # DEF → defensa
    2: (0.5, 0.5),  # MID → mixto
    3: (1.0, 0.0),  # ATT → ataque
}


def _weighted(values: list[tuple[float, float]]) -> float | None:
    """Media ponderada: values = [(rating, weight)]. None si peso total 0."""
    num = sum(r * w for r, w in values)
    den = sum(w for _, w in values)
    return (num / den) if den > 0 else None


def _team_row(date: str, code: str, starters: list[dict], lineup_type: str) -> dict | None:
    """Fila de fuerza para un equipo; None si ningún titular tiene season_rating."""
    rated = [p for p in starters if isinstance(p.get("season_rating"), (int, float))]
    if not rated:
        return None
    ratings = [float(p["season_rating"]) for p in rated]
    att_vals: list[tuple[float, float]] = []
    def_vals: list[tuple[float, float]] = []
    for p in rated:
        r = float(p["season_rating"])
        pos = p.get("usual_position_id")
        if pos is None:
            pos = p.get("position_id")
        w_att, w_def = _POS_WEIGHTS.get(pos if isinstance(pos, int) else -1, (0.5, 0.5))
        att_vals.append((r, w_att))
        def_vals.append((r, w_def))
    return {
        "date": date,
        "team_code": code,
        "xi_rating": round(sum(ratings) / len(ratings), 4),
        "att_rating": round(_weighted(att_vals) or 0.0, 4),
        "def_rating": round(_weighted(def_vals) or 0.0, 4),
        "n_starters": len(rated),
        "lineup_type": lineup_type,
    }


def build_lineup_strength(bronze_dir: Path | str = DEFAULT_BRONZE_DIR) -> pd.DataFrame:
    """Construye la tabla de fuerza de alineación desde el bronze (R3, R4).

    SI no existe ``bronze/lineups/`` → DataFrame vacío con el esquema (no rompe, R4).
    """
    lineups_dir = Path(bronze_dir) / "lineups"
    rows: list[dict] = []
    if lineups_dir.is_dir():
        for path in sorted(lineups_dir.glob("*.json")):
            if path.name.endswith(".meta.json"):
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Bronze lineup ilegible, omitiendo: %s (%s)", path, exc)
                continue
            date = doc.get("date", "")
            lt = doc.get("lineup_type", "")
            for side in ("home", "away"):
                code = doc.get(f"{side}_code")
                if not code or not date:
                    continue
                row = _team_row(date, code, doc.get(side) or [], lt)
                if row is not None:
                    rows.append(row)
    df = pd.DataFrame(rows, columns=list(LINEUP_STRENGTH_COLUMNS))
    if not df.empty:
        df = df.sort_values(["date", "team_code"], kind="mergesort").reset_index(drop=True)
    return df


def write_lineup_strength(df: pd.DataFrame, gold_dir: Path | str = DEFAULT_GOLD_DIR) -> Path:
    gold_dir = Path(gold_dir)
    gold_dir.mkdir(parents=True, exist_ok=True)
    path = gold_dir / "lineup_strength.csv"
    df.to_csv(path, index=False)
    return path
