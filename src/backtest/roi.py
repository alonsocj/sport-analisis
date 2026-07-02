"""src/backtest/roi.py — ROI opcional contra CSV de cuotas del usuario (R8).

Esquema CSV documentado (unico contrato publico)::

    date,home_code,away_code,odds_home,odds_draw,odds_away

Decimales europeos (> 1.0). Matching por ``(date, home_code, away_code)`` contra
los partidos evaluados. Value bet: ``prob_modelo_k * cuota_k > 1 + umbral``,
apuesta plana de 1 unidad por desenlace con value. Filas malformadas (cuota <= 1.0,
fecha invalida, columnas faltantes) se descartan con conteo. Si el CSV no existe o
no hay matches, la seccion ROI se omite con aviso (sin fallo).
"""

from __future__ import annotations

import csv
import warnings
from dataclasses import dataclass
from pathlib import Path

from .walkforward import WindowPrediction

# Cabecera exacta del esquema de cuotas (R8, design.md)
ODDS_COLUMNS = ("date", "home_code", "away_code", "odds_home", "odds_draw", "odds_away")


@dataclass
class ROIResult:
    """Resultado de la evaluacion de ROI (R8).

    Attributes:
        n_bets: Total number of bets placed.
        n_wins: Number of winning bets.
        stake: Total stake (n_bets * 1 unit).
        retorno: Total return from winning bets.
        roi: Return on investment = (retorno - stake) / stake.
        n_descartes_cuotas: Number of discarded odds rows (malformed).
        n_sin_match: Number of odds rows with no matching prediction.
    """

    n_bets: int
    n_wins: int
    stake: float
    retorno: float
    roi: float
    n_descartes_cuotas: int
    n_sin_match: int


def _parse_odds_row(row: dict[str, str]) -> tuple[str, str, str, float, float, float] | None:
    """Parsea y valida una fila del CSV de cuotas (R8).

    Descarta filas con columnas faltantes, cuotas no numericas, cuotas <= 1.0
    o fechas vacias.

    Args:
        row: Raw CSV row dict.

    Returns:
        Tuple of (date, home_code, away_code, odds_home, odds_draw, odds_away)
        or None if the row is malformed.
    """
    for col in ODDS_COLUMNS:
        if col not in row or not str(row[col]).strip():
            return None

    date_str = str(row["date"]).strip()
    home_code = str(row["home_code"]).strip()
    away_code = str(row["away_code"]).strip()

    if not date_str or not home_code or not away_code:
        return None

    try:
        odds_home = float(row["odds_home"])
        odds_draw = float(row["odds_draw"])
        odds_away = float(row["odds_away"])
    except (ValueError, TypeError):
        return None

    # Cuotas europeas deben ser > 1.0 (R8)
    if odds_home <= 1.0 or odds_draw <= 1.0 or odds_away <= 1.0:
        return None

    return date_str, home_code, away_code, odds_home, odds_draw, odds_away


def load_odds(
    odds_csv: Path | str,
) -> tuple[list[tuple[str, str, str, float, float, float]], int] | None:
    """Carga y valida el CSV de cuotas del usuario (R8).

    Si el archivo no existe, devuelve None (la seccion ROI se omite).
    Si existe pero no se puede leer como CSV valido, devuelve None con aviso.

    Args:
        odds_csv: Path to the odds CSV file.

    Returns:
        Tuple of (list of valid odds rows, n_descartes) or None if file not found.
    """
    path = Path(odds_csv)
    if not path.is_file():
        warnings.warn(
            f"CSV de cuotas no encontrado en {path}; la seccion ROI se omite (R8)",
            UserWarning,
            stacklevel=2,
        )
        return None

    valid_rows: list[tuple[str, str, str, float, float, float]] = []
    n_descartes = 0

    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            # Verificar que la cabecera tiene las columnas requeridas
            if reader.fieldnames is None:
                warnings.warn(
                    f"CSV de cuotas vacio en {path}; la seccion ROI se omite (R8)",
                    UserWarning,
                    stacklevel=2,
                )
                return None

            missing_cols = [c for c in ODDS_COLUMNS if c not in (reader.fieldnames or [])]
            if missing_cols:
                warnings.warn(
                    f"CSV de cuotas en {path} no tiene las columnas requeridas: "
                    f"{', '.join(missing_cols)}; la seccion ROI se omite (R8)",
                    UserWarning,
                    stacklevel=2,
                )
                return None

            for row in reader:
                parsed = _parse_odds_row(row)
                if parsed is None:
                    n_descartes += 1
                else:
                    valid_rows.append(parsed)
    except (OSError, csv.Error) as exc:
        warnings.warn(
            f"Error leyendo CSV de cuotas {path}: {exc}; la seccion ROI se omite (R8)",
            UserWarning,
            stacklevel=2,
        )
        return None

    return valid_rows, n_descartes


def evaluate_roi(
    predictions: list[WindowPrediction],
    odds_csv: Path | str,
    value_threshold: float = 0.05,
) -> ROIResult | None:
    """Evalua el ROI de apuesta plana con criterio de value bet (R8).

    Value bet: para cada desenlace k, apuesta plana de 1 unidad SI
    ``prob_modelo_k * cuota_k > 1 + umbral``. Se pueden hacer varias apuestas
    por partido si varios desenlaces tienen value. Matching por
    ``(date, home_code, away_code)``.

    SI el CSV no existe o no hay matches, devuelve None con aviso (sin fallo, R8).

    Args:
        predictions: List of evaluated window predictions.
        odds_csv: Path to the odds CSV file.
        value_threshold: Value threshold (default 0.05).

    Returns:
        ROIResult if any bets were placed, None if no CSV or no matches.
    """
    loaded = load_odds(odds_csv)
    if loaded is None:
        return None

    valid_rows, n_descartes = loaded

    if not valid_rows:
        warnings.warn(
            f"CSV de cuotas no tiene filas validas; la seccion ROI se omite (R8)",
            UserWarning,
            stacklevel=2,
        )
        return None

    # Indice de predicciones por (date, home_code, away_code) para matching rapido
    pred_index: dict[tuple[str, str, str], WindowPrediction] = {
        (p.date, p.home_code, p.away_code): p for p in predictions
    }

    n_bets = 0
    n_wins = 0
    stake = 0.0
    retorno = 0.0
    n_sin_match = 0

    for date_str, home_code, away_code, odds_home, odds_draw, odds_away in valid_rows:
        key = (date_str, home_code, away_code)
        pred = pred_index.get(key)
        if pred is None:
            n_sin_match += 1
            continue

        # Evaluar value bet para cada desenlace (R8)
        outcomes = [
            ("1", pred.prob_home, odds_home),
            ("X", pred.prob_draw, odds_draw),
            ("2", pred.prob_away, odds_away),
        ]
        for outcome_label, prob, odds in outcomes:
            if prob * odds > 1.0 + value_threshold:
                # Apuesta plana de 1 unidad
                n_bets += 1
                stake += 1.0
                if pred.actual == outcome_label:
                    n_wins += 1
                    retorno += odds

    if n_bets == 0:
        warnings.warn(
            "No se encontraron value bets con el umbral indicado; "
            "la seccion ROI se omite (R8)",
            UserWarning,
            stacklevel=2,
        )
        return None

    roi = (retorno - stake) / stake if stake > 0.0 else 0.0
    return ROIResult(
        n_bets=n_bets,
        n_wins=n_wins,
        stake=stake,
        retorno=retorno,
        roi=roi,
        n_descartes_cuotas=n_descartes,
        n_sin_match=n_sin_match,
    )
