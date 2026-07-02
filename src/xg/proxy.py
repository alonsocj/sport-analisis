"""src/xg/proxy.py — Proxy de xG por equipo/partido y serie objetivo mezclada (Feature 15, R2–R4).

Normaliza estadísticas de tiros desde el bronze de Wikipedia, empareja al silver por
(match_id, team_code), calcula el proxy de xG mediante la fórmula documentada, reporta
la cobertura (%) y construye la serie objetivo mezclada ``goal_target = (1−v)·goles + v·xg``
para alimentar el modelo Dixon-Coles (R4).

Fórmula del proxy (R3):
    xg_proxy = α·SoT + β·(shots − SoT)
    α ≈ 0.30  (conversión esperada de un tiro a puerta según tasas históricas WC)
    β ≈ 0.03  (conversión de un tiro fuera de puerta)
    Basado en tasas medias de conversión: ~30% de SoT acaban en gol; tiros fuera
    tienen ~3% de chance. Acotado a ≥ 0. Es un proxy grueso; no reemplaza un modelo
    de tiros con localización (documentado como limitación en requirements.md).

    Donde solo haya posesión (sin tiros) → sin xg_proxy (sin cobertura).

Serie objetivo (R4):
    goal_target_i = (1−v)·goals_i + v·xg_i   solo si cobertura
    goal_target_i = goals_i                    sin cobertura (comportamiento v1)
    v=0 ⇒ serie = goles exactos ⇒ ajuste idéntico a v1 (tol 1e-9).

Anti-fuga: el filtro fecha < as_of en load_training_data del Dixon-Coles garantiza que
el xG de un partido nunca informa la predicción de ese mismo partido (R4).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Parámetros del proxy xG (R3 — documentados, ajustables, no hardcodeados como magia).
# α: conversión esperada de un tiro a puerta (on-target shot → goal rate, ~30% histórico WC).
# β: conversión de un tiro fuera de puerta (~3% histórico).
ALPHA_DEFAULT: float = 0.30
BETA_DEFAULT: float = 0.03

# Nombres de columna del contrato de stats de Wikipedia (R2).
_COL_SHOTS = "shots"
_COL_SOT = "shots_on_target"
_COL_POSSESSION = "possession"
_COL_XG = "xg_proxy"
_COL_HAS_COVERAGE = "has_coverage"

# Columnas del silver consumidas para el emparejamiento (R2).
_SILVER_REQUIRED = ("match_id", "date", "home_code", "away_code", "home_goals", "away_goals")


@dataclass(frozen=True)
class StatsRow:
    """Estadísticas de un equipo en un partido (R2).

    Attributes:
        match_id: Unique match identifier from silver.
        team_code: FIFA three-letter team code.
        shots: Total shots attempted.
        shots_on_target: Shots on target (SoT).
        possession: Ball possession percentage (0–100).
    """

    match_id: str
    team_code: str
    shots: int | None
    shots_on_target: int | None
    possession: float | None


def compute_xg_proxy(
    shots: int | float | None,
    shots_on_target: int | float | None,
    alpha: float = ALPHA_DEFAULT,
    beta: float = BETA_DEFAULT,
) -> float | None:
    """Calcula el proxy de xG para un equipo/partido (R3).

    Fórmula: xg = α·SoT + β·(shots − SoT). Acotado a ≥ 0.
    Si los datos de tiros no están disponibles → None (sin cobertura).

    Args:
        shots: Total shots (None si no disponible).
        shots_on_target: Shots on target (None si no disponible).
        alpha: Conversion rate for shots on target (default 0.30).
        beta: Conversion rate for shots off target (default 0.03).

    Returns:
        xg_proxy float value, or None if inputs are unavailable.
    """
    if shots is None or shots_on_target is None:
        return None
    sot = float(shots_on_target)
    off_target = float(shots) - sot
    xg = alpha * sot + beta * max(off_target, 0.0)
    return max(xg, 0.0)


def _load_silver(silver_path: Path) -> pd.DataFrame:
    """Carga el silver y valida las columnas requeridas (R2).

    Args:
        silver_path: Path to silver matches CSV.

    Returns:
        DataFrame with silver match data.

    Raises:
        FileNotFoundError: If silver file does not exist.
        ValueError: If required columns are missing.
    """
    if not silver_path.is_file():
        raise FileNotFoundError(f"No existe el silver: {silver_path}")
    df = pd.read_csv(silver_path)
    missing = [c for c in _SILVER_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            f"Faltan columnas del contrato silver en {silver_path}: {', '.join(missing)}"
        )
    return df


def _load_wiki_stats(bronze_wiki_dir: Path) -> list[StatsRow]:
    """Carga todos los JSON de stats de Wikipedia desde el directorio bronze (R2).

    Cada archivo ``<slug>.json`` en ``data/bronze/wikipedia/`` se parsea; si le
    faltan las columnas de tiros, se trata como sin cobertura (no aborta).

    Args:
        bronze_wiki_dir: Directory containing Wikipedia bronze JSON files.

    Returns:
        List of StatsRow objects, one per (match_id, team_code) with available data.
    """
    rows: list[StatsRow] = []
    if not bronze_wiki_dir.is_dir():
        return rows
    for json_file in sorted(bronze_wiki_dir.glob("*.json")):
        if json_file.name.endswith(".meta.json"):
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        stats_list = data.get("stats", [])
        if not isinstance(stats_list, list):
            continue
        for entry in stats_list:
            if not isinstance(entry, dict):
                continue
            match_id = str(entry.get("match_id", "")).strip()
            team_code = str(entry.get("team_code", "")).strip()
            if not match_id or not team_code:
                continue
            rows.append(
                StatsRow(
                    match_id=match_id,
                    team_code=team_code,
                    shots=_safe_int(entry.get("shots")),
                    shots_on_target=_safe_int(entry.get("shots_on_target")),
                    possession=_safe_float(entry.get("possession")),
                )
            )
    return rows


def _safe_int(value: object) -> int | None:
    """Convierte a int de forma segura; None si no es convertible."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    """Convierte a float de forma segura; None si no es convertible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_xg_table(
    silver_path: Path,
    bronze_wiki_dir: Path,
    alpha: float = ALPHA_DEFAULT,
    beta: float = BETA_DEFAULT,
) -> pd.DataFrame:
    """Empareja stats de Wikipedia al silver y calcula xg_proxy (R2, R3).

    Produce una tabla por (match_id, team_code) con columnas:
    match_id, team_code, shots, shots_on_target, possession, xg_proxy, has_coverage.

    Partidos del silver sin stats de Wikipedia → ``has_coverage=False``, valores None.
    Reporta el % de cobertura (home + away por partido = 2 filas por partido) (R2).

    Args:
        silver_path: Path to silver matches CSV.
        bronze_wiki_dir: Directory containing Wikipedia bronze JSON files.
        alpha: xG proxy alpha parameter (SoT conversion rate).
        beta: xG proxy beta parameter (off-target conversion rate).

    Returns:
        DataFrame with columns: match_id, team_code, shots, shots_on_target,
        possession, xg_proxy, has_coverage.
    """
    silver = _load_silver(silver_path)
    wiki_rows = _load_wiki_stats(bronze_wiki_dir)

    # Construir tabla base de (match_id, team_code) desde el silver: home y away
    base_records = []
    for _, row in silver.iterrows():
        for team_col in ("home_code", "away_code"):
            base_records.append({
                "match_id": str(row["match_id"]),
                "team_code": str(row[team_col]),
            })
    base_df = pd.DataFrame(base_records)

    # Tabla de stats wiki indexada por (match_id, team_code)
    wiki_lookup: dict[tuple[str, str], StatsRow] = {
        (r.match_id, r.team_code): r for r in wiki_rows
    }

    # Enriquecer base con stats (R2)
    records = []
    for _, brow in base_df.iterrows():
        key = (str(brow["match_id"]), str(brow["team_code"]))
        wiki = wiki_lookup.get(key)
        if wiki is not None and (wiki.shots is not None and wiki.shots_on_target is not None):
            xg = compute_xg_proxy(wiki.shots, wiki.shots_on_target, alpha, beta)
            records.append({
                "match_id": key[0],
                "team_code": key[1],
                "shots": wiki.shots,
                "shots_on_target": wiki.shots_on_target,
                "possession": wiki.possession,
                "xg_proxy": xg,
                "has_coverage": True,
            })
        else:
            records.append({
                "match_id": key[0],
                "team_code": key[1],
                "shots": None,
                "shots_on_target": None,
                "possession": wiki.possession if wiki else None,
                "xg_proxy": None,
                "has_coverage": False,
            })

    return pd.DataFrame(records)


def coverage_report(xg_table: pd.DataFrame) -> dict[str, float]:
    """Calcula el porcentaje de cobertura del proxy xG (R2).

    La cobertura se mide a nivel de (match_id, team_code): cuántas filas tienen
    xg_proxy disponible (has_coverage=True) sobre el total.

    Args:
        xg_table: DataFrame produced by build_xg_table.

    Returns:
        Dict with keys: n_total, n_covered, coverage_pct.
    """
    n_total = len(xg_table)
    n_covered = int(xg_table["has_coverage"].sum())
    coverage_pct = 100.0 * n_covered / n_total if n_total > 0 else 0.0
    return {
        "n_total": n_total,
        "n_covered": n_covered,
        "coverage_pct": coverage_pct,
    }


def build_goal_target_series(
    silver_path: Path,
    xg_table: pd.DataFrame,
    v: float,
) -> pd.DataFrame:
    """Construye la serie objetivo mezclada goal_target por partido/equipo (R4).

    ``goal_target = (1−v)·goles + v·xg_proxy`` solo donde hay cobertura.
    Sin cobertura (has_coverage=False) → ``goal_target = goles`` (comportamiento v1).
    Con v=0 → serie idéntica a los goles reales para todos los partidos (no-regresión).

    La tabla devuelta puede alimentar directamente a load_training_data mediante el
    parámetro ``xg_target_map`` (R4). Anti-fuga: el filtro fecha < as_of en
    load_training_data garantiza que el xG de un partido nunca predice ese partido.

    Args:
        silver_path: Path to silver matches CSV.
        xg_table: DataFrame from build_xg_table with has_coverage and xg_proxy columns.
        v: Blend weight ∈ [0, 1]. v=0 → pure goals (v1 behaviour, tol 1e-9).

    Returns:
        DataFrame with columns: match_id, team_code, goals, xg_proxy,
        has_coverage, goal_target.

    Raises:
        ValueError: If v is not in [0, 1].
    """
    if not (0.0 <= v <= 1.0):
        raise ValueError(f"v debe estar en [0, 1]; recibido: {v}")

    silver = _load_silver(silver_path)

    # Desnormalizar silver a (match_id, team_code, goals)
    home_goals = silver[["match_id", "home_code", "home_goals"]].rename(
        columns={"home_code": "team_code", "home_goals": "goals"}
    )
    away_goals = silver[["match_id", "away_code", "away_goals"]].rename(
        columns={"away_code": "team_code", "away_goals": "goals"}
    )
    goals_df = pd.concat([home_goals, away_goals], ignore_index=True)
    goals_df["match_id"] = goals_df["match_id"].astype(str)
    goals_df["team_code"] = goals_df["team_code"].astype(str)

    # Join con xg_table
    xg_sub = xg_table[["match_id", "team_code", "xg_proxy", "has_coverage"]].copy()
    xg_sub["match_id"] = xg_sub["match_id"].astype(str)
    xg_sub["team_code"] = xg_sub["team_code"].astype(str)

    merged = goals_df.merge(xg_sub, on=["match_id", "team_code"], how="left")
    merged["has_coverage"] = merged["has_coverage"].fillna(False)

    # Calcular goal_target (R4)
    def _blend(row: pd.Series) -> float:
        goals = float(row["goals"])
        if v == 0.0 or not row["has_coverage"] or pd.isna(row.get("xg_proxy")):
            return goals
        return (1.0 - v) * goals + v * float(row["xg_proxy"])

    merged["goal_target"] = merged.apply(_blend, axis=1)
    return merged
