"""src/eval/prediction_log.py — Registro de predicciones append-only para el Mundial 2026 (R1–R5, R8 F14).

Genera predicciones 1X2 + lambda + mercados opcionales (O/U 2.5, BTTS) para fixtures
objetivo y las persiste en ``data/predictions/log.csv`` con upsert determinista por
clave (``match_id``, ``as_of_date``, ``model_version``).

Contratos:
- ``created_at`` SIEMPRE inyectado (argumento ISO-8601), nunca del reloj del sistema (R2).
- El filtro ``fecha < as_of_date`` de ``load_training_data`` garantiza anti-fuga (R3).
- Upsert por clave; archivo ordenado por ``(match_date, match_id, as_of_date)`` (R4).
- Equipos fuera del recorte del modelo → ``skipped`` con motivo, sin abortar (R5).
- En producción, la escritura se realiza bajo ``data/predictions/`` (``log.csv``).
- Con ``elo_weight > 0``: aplica ensemble ``(1−w)·p_DC + w·p_Elo`` usando
  ``elo_history`` as-of (leak-free, R8 F14); etiqueta ``model_version = "dc-ens"``.
  Con ``elo_weight = 0``: comportamiento idéntico al actual (no-regresión, R5 F14).
"""

from __future__ import annotations

import csv
import io
import warnings
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ..markets.goals import prob_btts, prob_over
from ..models.dixon_coles import (
    DCConfig,
    DixonColesParams,
    UnknownTeamError,
    fit_dixon_coles,
    predict_match,
)
from .evaluate import _assert_under_data

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

MODEL_VERSION = "dc-v1"
MODEL_VERSION_V2 = "dc-v2"
MODEL_VERSION_ENS = "dc-ens"  # Ensemble DC + Elo (R8 F14)

DEFAULT_LOG_PATH = Path("data/predictions/log.csv")

# Columnas del contrato del log (R1) — orden fijo, inmutable.
LOG_COLUMNS: tuple[str, ...] = (
    "created_at",
    "model_version",
    "as_of_date",
    "match_date",
    "match_id",
    "home_code",
    "away_code",
    "p_home",
    "p_draw",
    "p_away",
    "lambda_home",
    "lambda_away",
    "p_over25",
    "p_btts",
    "neutral",
)

# Clave de upsert (R4).
UPSERT_KEY: tuple[str, ...] = ("match_id", "as_of_date", "model_version")

# Orden determinista del archivo (R4).
SORT_COLUMNS: list[str] = ["match_date", "match_id", "as_of_date"]


# ---------------------------------------------------------------------------
# Helpers de validación
# ---------------------------------------------------------------------------


def _validate_iso_datetime(value: str, name: str) -> None:
    """Valida formato ISO-8601 básico para timestamp (R2).

    Acepta ``YYYY-MM-DDTHH:MM:SS`` con o sin zona horaria / microsegundos.

    Args:
        value: The ISO-8601 string to validate.
        name: Parameter name for the error message.

    Raises:
        ValueError: If value is not a valid ISO-8601 datetime.
    """
    from datetime import datetime

    try:
        # Intentar parsear con fromisoformat (Python 3.11+ acepta tz correctamente).
        datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{name} debe ser ISO-8601 (ej. '2026-06-11T10:00:00Z'); "
            f"recibido: {value!r} (R2)"
        )


def _validate_iso_date(value: str, name: str) -> None:
    """Valida formato estricto YYYY-MM-DD.

    Args:
        value: The date string to validate.
        name: Parameter name for the error message.

    Raises:
        ValueError: If value is not a valid YYYY-MM-DD date.
    """
    try:
        ok = date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise ValueError(
            f"{name} debe tener formato YYYY-MM-DD; recibido: {value!r}"
        )


# ---------------------------------------------------------------------------
# Generación de predicciones para un fixture (R1, R2, R3)
# ---------------------------------------------------------------------------


def _predict_row(
    params: DixonColesParams,
    match_date: str,
    match_id: str,
    home_code: str,
    away_code: str,
    neutral: bool,
    created_at: str,
    as_of_date: str,
    include_markets: bool,
    model_version: str = MODEL_VERSION,
    elo_weight: float = 0.0,
    elo_history: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Genera una fila del log para un fixture dado.

    Usa ``predict_match`` del modelo Dixon-Coles. Calcula mercados opcionales
    (``p_over25`` vía O/U 2.5 de la matriz, ``p_btts``) solo cuando ``include_markets``.
    Las columnas de mercado quedan vacías ('') cuando no se piden (R1).

    Con ``elo_weight > 0`` aplica el ensemble ``(1−w)·p_DC + w·p_Elo`` usando
    ``elo_history`` as-of (``date < as_of_date``, leak-free, R8 F14). El
    ``model_version`` se fuerza a ``"dc-ens"`` automáticamente cuando ``w > 0``.
    Con ``elo_weight = 0`` el resultado es IDÉNTICO al DC puro (R5 F14).

    Args:
        params: Trained Dixon-Coles parameters.
        match_date: Match date string (YYYY-MM-DD).
        match_id: Stable match identifier from silver.
        home_code: FIFA code of the home team.
        away_code: FIFA code of the away team.
        neutral: Whether the match is played at a neutral venue.
        created_at: Injected ISO-8601 timestamp (R2).
        as_of_date: Training cutoff date (R3).
        include_markets: Whether to compute p_over25 and p_btts (R1, R9).
        model_version: Version tag written to the log.
        elo_weight: Blend weight w ∈ [0, 1] for the Elo sub-model (R8 F14).
            0.0 = pure DC (no change). With w > 0, uses elo_history as-of.
        elo_history: elo_history DataFrame for the ensemble (R8 F14).
            Required when elo_weight > 0.

    Returns:
        Dict with LOG_COLUMNS as keys.

    Raises:
        UnknownTeamError: If home_code or away_code not in trained params.
    """
    pred = predict_match(params, home_code, away_code)

    # Aplicar ensemble DC + Elo si w > 0 (R8 F14)
    prob_home = pred.prob_home
    prob_draw = pred.prob_draw
    prob_away = pred.prob_away
    effective_version = model_version

    if elo_weight > 0.0 and elo_history is not None:
        from ..elo_ext.model import predict_elo, EloModelParams
        from ..elo_ext.ensemble import ensemble

        # Elo as-of (date < as_of_date) — leak-free, R7 F14
        p_elo = predict_elo(
            home_code=home_code,
            away_code=away_code,
            as_of_date=as_of_date,
            history=elo_history,
            neutral=neutral,
        )
        p_ens = ensemble(
            (prob_home, prob_draw, prob_away),
            p_elo,
            w=elo_weight,
        )
        prob_home = p_ens.prob_home
        prob_draw = p_ens.prob_draw
        prob_away = p_ens.prob_away
        effective_version = MODEL_VERSION_ENS  # etiqueta "dc-ens" (R8 F14)

    p_over25: str | float = ""
    p_btts_val: str | float = ""
    if include_markets:
        p_over25 = prob_over(pred.matrix, 2.5)
        p_btts_val = prob_btts(pred.matrix)

    return {
        "created_at": created_at,
        "model_version": effective_version,
        "as_of_date": as_of_date,
        "match_date": match_date,
        "match_id": match_id,
        "home_code": home_code,
        "away_code": away_code,
        "p_home": prob_home,
        "p_draw": prob_draw,
        "p_away": prob_away,
        "lambda_home": pred.lambda_home,
        "lambda_away": pred.lambda_away,
        "p_over25": p_over25,
        "p_btts": p_btts_val,
        "neutral": neutral,
    }


# ---------------------------------------------------------------------------
# Upsert determinista (R4)
# ---------------------------------------------------------------------------


def _upsert(existing: pd.DataFrame, new_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Aplica upsert por clave (UPSERT_KEY) y reordena deterministicamente (R4).

    Las filas de ``new_rows`` reemplazan las existentes con la misma clave.
    El resultado queda ordenado por SORT_COLUMNS con valores string, sin duplicados.

    Args:
        existing: Current log DataFrame (puede estar vacío).
        new_rows: New rows to upsert.

    Returns:
        Updated and sorted DataFrame with LOG_COLUMNS.
    """
    if not new_rows:
        return existing

    new_df = pd.DataFrame(new_rows, columns=list(LOG_COLUMNS))

    if existing.empty:
        combined = new_df
    else:
        # Elimina del existente las filas con la misma clave (R4)
        key_tuples_new = set(
            zip(new_df["match_id"], new_df["as_of_date"], new_df["model_version"])
        )
        mask_keep = ~existing.apply(
            lambda r: (r["match_id"], r["as_of_date"], r["model_version"])
            in key_tuples_new,
            axis=1,
        )
        combined = pd.concat([existing[mask_keep], new_df], ignore_index=True)

    # Orden determinista (R4)
    combined = combined.sort_values(SORT_COLUMNS, kind="mergesort").reset_index(drop=True)
    return combined


# ---------------------------------------------------------------------------
# Lectura/escritura del log
# ---------------------------------------------------------------------------


def _read_log(log_path: Path) -> pd.DataFrame:
    """Lee el log CSV existente; retorna DataFrame vacío si no existe.

    Args:
        log_path: Path to the log CSV file.

    Returns:
        DataFrame with LOG_COLUMNS, or empty DataFrame if file does not exist.
    """
    if not log_path.is_file():
        return pd.DataFrame(columns=list(LOG_COLUMNS))
    df = pd.read_csv(log_path, dtype=str)
    # Asegurar que todas las columnas del contrato existen
    for col in LOG_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[list(LOG_COLUMNS)]


def _write_log(df: pd.DataFrame, log_path: Path) -> None:
    """Escribe el log CSV con columnas en orden fijo del contrato (R1, R4).

    Args:
        df: DataFrame with LOG_COLUMNS.
        log_path: Destination path.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    df[list(LOG_COLUMNS)].to_csv(log_path, index=False)


# ---------------------------------------------------------------------------
# Fixtures objetivo (R5)
# ---------------------------------------------------------------------------


def fixtures_from_csv(csv_path: Path | str) -> list[dict[str, Any]]:
    """Carga fixtures desde un CSV con columnas mínimas requeridas.

    Columnas esperadas: ``date``, ``match_id``, ``home_code``, ``away_code``.
    La columna ``neutral`` es opcional (default ``False``).

    Args:
        csv_path: Path to the fixtures CSV file.

    Returns:
        List of fixture dicts with keys: date, match_id, home_code, away_code, neutral.

    Raises:
        ValueError: If required columns are missing.
    """
    df = pd.read_csv(Path(csv_path), dtype=str)
    required = ["date", "match_id", "home_code", "away_code"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"CSV de fixtures falta columnas: {', '.join(missing)}")
    if "neutral" not in df.columns:
        df["neutral"] = "False"
    rows = []
    for _, row in df.iterrows():
        neutral_val = str(row["neutral"]).strip().lower() in ("true", "1", "yes")
        rows.append({
            "date": str(row["date"]).strip(),
            "match_id": str(row["match_id"]).strip(),
            "home_code": str(row["home_code"]).strip(),
            "away_code": str(row["away_code"]).strip(),
            "neutral": neutral_val,
        })
    return rows


def fixtures_from_schedule(results_csv: Path | str) -> list[dict[str, Any]]:
    """Fixtures pendientes del WC2026 desde el bronze (reusa lógica de schedule, R5).

    Reutiliza el mismo patrón que ``_pending_world_cup_rows`` de ``src/cli.py``:
    lee el CSV crudo, filtra ``tournament == 'FIFA World Cup'`` y descarta los que
    ya tienen marcador numérico. Genera un ``match_id`` estable por ``date+home+away``.

    Args:
        results_csv: Path to the public bronze results CSV.

    Returns:
        List of fixture dicts with keys: date, match_id, home_code, away_code, neutral.

    Raises:
        FileNotFoundError: If the results CSV does not exist.
    """
    from ..ingestion.public_data import to_fifa_code

    csv_path = Path(results_csv)
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"No existe el bronze público en {csv_path}; "
            "ejecuta `ingest-public` primero"
        )

    def _is_int(val: object) -> bool:
        try:
            int(val)  # type: ignore[arg-type]
            return True
        except (TypeError, ValueError):
            return False

    rows: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not row.get("date") or not row.get("home_team") or not row.get("away_team"):
                continue
            if row.get("tournament") != "FIFA World Cup":
                continue
            if _is_int(row.get("home_score")) and _is_int(row.get("away_score")):
                continue  # ya jugado
            home_name = row["home_team"]
            away_name = row["away_team"]
            home_code = to_fifa_code(home_name) or home_name
            away_code = to_fifa_code(away_name) or away_name
            # match_id estable: date + home_code + away_code
            match_id = f"{row['date']}_{home_code}_{away_code}"
            neutral_str = str(row.get("neutral", "")).strip().lower()
            neutral_val = neutral_str in ("true", "1", "yes")
            rows.append({
                "date": row["date"],
                "match_id": match_id,
                "home_code": home_code,
                "away_code": away_code,
                "neutral": neutral_val,
            })

    rows.sort(key=lambda r: (r["date"], r["home_code"], r["away_code"]))
    return rows


# ---------------------------------------------------------------------------
# Función principal: log_predictions (R1–R5)
# ---------------------------------------------------------------------------


def log_predictions(
    as_of_date: str,
    created_at: str,
    fixtures: list[dict[str, Any]],
    include_markets: bool = False,
    silver_path: Path | str = Path("data/silver/matches.csv"),
    log_path: Path | str = DEFAULT_LOG_PATH,
    config: DCConfig = DCConfig(),
    model_version: str = MODEL_VERSION,
    importance_map: dict[str, float] | None = None,
    elo_weight: float = 0.0,
    elo_history_path: Path | str | None = None,
) -> dict[str, Any]:
    """Genera y persiste predicciones para una lista de fixtures (R1–R5, R5 feature 12, R8 F14).

    Entrena el modelo Dixon-Coles con datos ``fecha < as_of_date`` (anti-fuga, R3),
    genera predicciones por fixture y escribe el log con upsert (R4).

    Con ``elo_weight > 0``: aplica el ensemble ``(1−w)·p_DC + w·p_Elo`` usando
    ``elo_history`` as-of (leak-free, R8 F14). El ``model_version`` registrado será
    automáticamente ``"dc-ens"``. Con ``elo_weight = 0``: comportamiento IDÉNTICO
    a la versión anterior (cero regresión, R5 F14).

    Args:
        as_of_date: Training cutoff date (YYYY-MM-DD). Used for anti-leakage (R3).
        created_at: Injected ISO-8601 timestamp for all rows (R2). Never from the system clock.
        fixtures: List of fixture dicts with keys: date, match_id, home_code,
            away_code, neutral.
        include_markets: If True, compute p_over25 and p_btts (R1).
        silver_path: Path to silver matches CSV for training.
        log_path: Destination path for the log CSV (must be under data/).
        config: Dixon-Coles configuration for training.
        model_version: Version tag written to the log (R5 feature 12).
            Default ``"dc-v1"``; use ``"dc-v2"`` for rolling refit with importance.
            When elo_weight > 0, this is overridden to ``"dc-ens"`` (R8 F14).
        importance_map: Optional dict ``{tournament: factor}`` for v2 weighting
            (R5 feature 12).  ``None`` → v1 behaviour.
        elo_weight: Blend weight w ∈ [0, 1] for the Elo sub-model (R8 F14).
            0.0 = pure DC (no change). With w > 0, elo_history is loaded and
            used as-of to blend probabilities (leak-free).
        elo_history_path: Path to the elo_history CSV (gold). If None, uses
            the default path ``data/gold/elo_history.csv``. Only used when
            elo_weight > 0.

    Returns:
        Dict with keys: ``n_logged`` (int), ``n_skipped`` (int),
        ``skipped`` (list of dicts with match_id and reason).

    Raises:
        ValueError: If as_of_date or created_at are malformed.
    """
    _validate_iso_date(as_of_date, "as_of_date")
    _validate_iso_datetime(created_at, "created_at")
    _assert_under_data(Path(log_path))

    # Entrenar el modelo con datos < as_of_date (R3 — anti-fuga)
    params: DixonColesParams = fit_dixon_coles(
        as_of_date, silver_path=silver_path, config=config,
        importance_map=importance_map,
    )

    # Cargar elo_history si se requiere el ensemble (R8 F14)
    elo_history: pd.DataFrame | None = None
    if elo_weight > 0.0:
        from ..elo_ext.model import DEFAULT_GOLD_ELO_HISTORY
        hist_path = Path(elo_history_path) if elo_history_path else DEFAULT_GOLD_ELO_HISTORY
        if hist_path.is_file():
            elo_history = pd.read_csv(hist_path)
        else:
            warnings.warn(
                f"elo_history no encontrado en {hist_path}; "
                f"elo_weight={elo_weight} ignorado, usando DC puro",
                UserWarning,
                stacklevel=2,
            )

    log_path = Path(log_path)
    existing = _read_log(log_path)

    new_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for fix in fixtures:
        home = fix["home_code"]
        away = fix["away_code"]
        try:
            row = _predict_row(
                params=params,
                match_date=fix["date"],
                match_id=fix["match_id"],
                home_code=home,
                away_code=away,
                neutral=fix.get("neutral", False),
                created_at=created_at,
                as_of_date=as_of_date,
                include_markets=include_markets,
                model_version=model_version,
                elo_weight=elo_weight,
                elo_history=elo_history,
            )
            new_rows.append(row)
        except UnknownTeamError:
            skipped.append({
                "match_id": fix["match_id"],
                "reason": "equipo_fuera_de_recorte",
            })

    updated = _upsert(existing, new_rows)
    _write_log(updated, log_path)

    return {
        "n_logged": len(new_rows),
        "n_skipped": len(skipped),
        "skipped": skipped,
    }
