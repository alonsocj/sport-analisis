"""Normalización de eventos de gol: bronze goalscorers → silver de eventos (R2).

Lee el CSV bronze de goleadores (``data/bronze/goalscorers/goalscorers.csv``) y
produce una tabla silver de eventos en memoria con las siguientes transformaciones:

- Filas con ``own_goal == TRUE`` se EXCLUYEN del crédito al goleador (no cuentan
  como gol del jugador), pero el flag ``penalty`` se conserva.
- El campo ``team`` (nombre del dataset) se mapea a código FIFA consistente con el
  silver de partidos mediante el mismo ``DATASET_ALIASES`` de ``public_data.py``.
- Filas malformadas (fecha inválida, scorer vacío, columnas incompletas, equipo sin
  código conocido) se descartan contabilizadas con motivo, sin abortar el lote.

Solo la función ``normalize_goalscorer_events`` es parte de la API pública del
módulo; la salida es un ``list[GoalEvent]`` más un ``NormalizeReport`` con los
descartes por motivo.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from ..ingestion.public_data import DATASET_ALIASES
from ..ingestion.goalscorers import DEFAULT_BRONZE_DIR, _strip_bom, EXPECTED_HEADER

# ---------------------------------------------------------------------------
# Constantes de motivo de descarte (R2)
# ---------------------------------------------------------------------------

REASON_INCOMPLETE_COLUMNS = "columnas_incompletas"
REASON_INVALID_DATE = "fecha_invalida"
REASON_OWN_GOAL = "own_goal_excluido"
REASON_EMPTY_SCORER = "scorer_vacio"
REASON_UNKNOWN_TEAM = "equipo_sin_codigo"


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoalEvent:
    """Evento de gol normalizado (R2).

    ``date``: ISO ``YYYY-MM-DD``; ``team_code``: código FIFA 3 letras;
    ``scorer``: nombre del goleador; ``penalty``: True si fue de penalti.
    """

    date: str
    team_code: str
    scorer: str
    penalty: bool


@dataclass
class NormalizeReport:
    """Reporte de normalización: totales y descartes por motivo (R2)."""

    n_rows_total: int
    n_valid: int
    n_discarded: int
    discarded_by_reason: dict[str, int]


# ---------------------------------------------------------------------------
# Helpers de validación
# ---------------------------------------------------------------------------


def _is_iso_date(value: str) -> bool:
    """True si ``value`` es exactamente ``YYYY-MM-DD`` (R2)."""
    try:
        return date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError):
        return False


def _parse_bool_flag(value: str) -> bool:
    """True si ``value`` (case-insensitive, stripped) == ``'true'`` (R2)."""
    return value.strip().upper() == "TRUE"


def _row_discard_reason(row: list[str]) -> str | None:
    """Motivo de descarte de una fila, o None si es válida (sin own_goal) (R2).

    Orden de verificación:
    1. Columnas incompletas.
    2. Fecha inválida.
    3. Scorer vacío.
    4. Own goal (excludido del crédito al goleador).
    5. Equipo sin código FIFA conocido.

    Returns None if the row is valid and should be included as a GoalEvent.
    Returns REASON_OWN_GOAL if the row is an own goal (explicitly excluded).
    Returns another reason string if the row is malformed.
    """
    if len(row) != len(EXPECTED_HEADER):
        return REASON_INCOMPLETE_COLUMNS
    date_val, _, _, team_val, scorer_val, _, own_goal_val, _ = row
    if not _is_iso_date(date_val):
        return REASON_INVALID_DATE
    if not scorer_val.strip():
        return REASON_EMPTY_SCORER
    if _parse_bool_flag(own_goal_val):
        return REASON_OWN_GOAL
    if team_val.strip() not in DATASET_ALIASES:
        return REASON_UNKNOWN_TEAM
    return None


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def normalize_goalscorer_events(
    csv_text: str,
) -> tuple[list[GoalEvent], NormalizeReport]:
    """Parseo tolerante fila a fila del CSV de goleadores (R2).

    Las filas corruptas (fecha inválida, scorer vacío, columnas incompletas,
    equipo sin código conocido) se descartan y cuentan por motivo en el
    :class:`NormalizeReport`; las filas de own_goal se excluyen del crédito y
    también se cuentan; el lote continúa siempre.

    Args:
        csv_text: Contenido del CSV bronze de goleadores.

    Returns:
        Tuple of (events, report).
    """
    rows = list(csv.reader(io.StringIO(_strip_bom(csv_text))))
    data_rows = rows[1:]  # sin encabezado

    events: list[GoalEvent] = []
    discarded_by_reason: dict[str, int] = {}

    for row in data_rows:
        reason = _row_discard_reason(row)
        if reason is not None:
            discarded_by_reason[reason] = discarded_by_reason.get(reason, 0) + 1
            continue
        # Fila válida: mapear a GoalEvent
        date_val, _, _, team_val, scorer_val, _, _, penalty_val = row
        events.append(
            GoalEvent(
                date=date_val.strip(),
                team_code=DATASET_ALIASES[team_val.strip()],
                scorer=scorer_val.strip(),
                penalty=_parse_bool_flag(penalty_val),
            )
        )

    report = NormalizeReport(
        n_rows_total=len(data_rows),
        n_valid=len(events),
        n_discarded=len(data_rows) - len(events),
        discarded_by_reason=discarded_by_reason,
    )
    return events, report


def load_bronze_goalscorers(
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
) -> tuple[list[GoalEvent], NormalizeReport]:
    """Carga el bronze de goleadores y normaliza los eventos (R2).

    Args:
        bronze_dir: Directorio raíz del bronze.

    Returns:
        Tuple of (events, report).

    Raises:
        FileNotFoundError: Si no existe el CSV bronze de goleadores.
    """
    from ..ingestion.goalscorers import bronze_goalscorers_paths

    csv_path, _ = bronze_goalscorers_paths(bronze_dir)
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"No existe el bronze de goleadores en {csv_path}; "
            "ejecuta primero `ingest-goalscorers`"
        )
    csv_text = csv_path.read_text(encoding="utf-8")
    return normalize_goalscorer_events(csv_text)
