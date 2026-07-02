"""Funciones puras de mercados de goles derivadas de la matriz Dixon-Coles (Feature 4).

Calcula probabilidades de over/under en lineas k+0.5, BTTS (ambos marcan) y
totales por equipo a partir de la matriz conjunta M[x][y] (goles del local en
filas, goles del visitante en columnas, suma 1, soporte 0..max_goals) del
contrato de la feature 3 (predict_match/score_matrix). Sin red, sin reloj,
sin RNG, sin importar streamlit ni modulos de red.

Public API:
    DEFAULT_TOTAL_LINES, DEFAULT_TEAM_LINES,
    MarketLine, MarketSummary,
    _validate_line, prob_over, prob_btts, prob_team_over,
    market_summary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ..models.dixon_coles import DixonColesParams, UnknownTeamError, predict_match

# ---------------------------------------------------------------------------
# Constantes de lineas por defecto (R2, R4)
# ---------------------------------------------------------------------------

DEFAULT_TOTAL_LINES: tuple[float, ...] = (0.5, 1.5, 2.5, 3.5, 4.5)
DEFAULT_TEAM_LINES: tuple[float, ...] = (0.5, 1.5, 2.5)


# ---------------------------------------------------------------------------
# Dataclasses inmutables de salida (R5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketLine:
    """Resultado de over/under para una linea dada.

    Attributes:
        line: The betting line (k + 0.5 form).
        over: Probability of going over the line.
        under: Probability of going under the line.
    """

    line: float
    over: float
    under: float


@dataclass(frozen=True)
class MarketSummary:
    """Resumen completo de mercados de goles para un partido.

    Attributes:
        home_code: FIFA code of the home team.
        away_code: FIFA code of the away team.
        prob_home: Probability of home win (1X2).
        prob_draw: Probability of draw (1X2).
        prob_away: Probability of away win (1X2).
        totals: Over/under market lines for total goals.
        btts_yes: Probability both teams score.
        btts_no: Probability at least one team does not score.
        home_totals: Over/under market lines for home team goals.
        away_totals: Over/under market lines for away team goals.
    """

    home_code: str
    away_code: str
    prob_home: float
    prob_draw: float
    prob_away: float
    totals: tuple[MarketLine, ...]
    btts_yes: float
    btts_no: float
    home_totals: tuple[MarketLine, ...]
    away_totals: tuple[MarketLine, ...]


# ---------------------------------------------------------------------------
# Validacion de lineas (R2, R4)
# ---------------------------------------------------------------------------


def _validate_line(line: float) -> None:
    """Valida que line sea de la forma k + 0.5 con k entero >= 0.

    Args:
        line: The line value to validate.

    Raises:
        ValueError: If line is not of the form k + 0.5 (k non-negative integer).
    """
    # line - 0.5 debe ser entero no negativo
    shifted = line - 0.5
    if shifted < 0 or not math.isclose(shifted, round(shifted), abs_tol=1e-9):
        raise ValueError(
            f"linea invalida: {line!r}; se espera formato k + 0.5 con k entero >= 0 "
            f"(ej. 0.5, 1.5, 2.5, ...)"
        )


# ---------------------------------------------------------------------------
# Funciones puras de calculo (R2, R3, R4)
# ---------------------------------------------------------------------------


def prob_over(matrix: np.ndarray, line: float) -> float:
    """Calcula P(total_goals > line) = P(X + Y > line) desde la matriz conjunta.

    Con lineas de la forma k + 0.5, la desigualdad estricta equivale a
    X + Y >= ceil(line), sin posibilidad de push.

    Args:
        matrix: Joint score probability matrix M[x][y], rows=home goals, cols=away.
        line: Betting line in k + 0.5 form.

    Returns:
        Float probability in [0, 1].
    """
    _validate_line(line)
    n = matrix.shape[0]
    total = 0.0
    threshold = int(math.ceil(line))  # k+0.5 → threshold = k+1
    for x in range(n):
        for y in range(matrix.shape[1]):
            if x + y >= threshold:
                total += matrix[x, y]
    return float(total)


def prob_btts(matrix: np.ndarray) -> float:
    """Calcula P(BTTS si) = P(X >= 1 AND Y >= 1) desde la matriz conjunta.

    Args:
        matrix: Joint score probability matrix M[x][y].

    Returns:
        Float probability in [0, 1].
    """
    return float(matrix[1:, 1:].sum())


def prob_team_over(
    matrix: np.ndarray,
    side: Literal["home", "away"],
    line: float,
) -> float:
    """Calcula P(goles del equipo > line) usando la marginal correspondiente.

    Home: marginal por filas (suma sobre columnas Y).
    Away: marginal por columnas (suma sobre filas X).

    Args:
        matrix: Joint score probability matrix M[x][y].
        side: 'home' for row marginal, 'away' for column marginal.
        line: Betting line in k + 0.5 form.

    Returns:
        Float probability in [0, 1].
    """
    _validate_line(line)
    threshold = int(math.ceil(line))  # k+0.5 → threshold = k+1
    if side == "home":
        # marginal home: suma cada fila x sobre todas las columnas y
        marginal = matrix.sum(axis=1)  # shape (n,)
        return float(marginal[threshold:].sum())
    else:
        # marginal away: suma cada columna y sobre todas las filas x
        marginal = matrix.sum(axis=0)  # shape (m,)
        return float(marginal[threshold:].sum())


# ---------------------------------------------------------------------------
# Funcion de resumen principal (R5)
# ---------------------------------------------------------------------------


def market_summary(
    params: DixonColesParams,
    home_code: str,
    away_code: str,
    total_lines: tuple[float, ...] = DEFAULT_TOTAL_LINES,
    team_lines: tuple[float, ...] = DEFAULT_TEAM_LINES,
) -> MarketSummary:
    """Calcula el resumen completo de mercados de goles para un partido.

    Llama a predict_match UNA sola vez y deriva todos los mercados de la
    matriz resultante. UnknownTeamError se propaga sin envolver (R5).
    Las lineas de salida estan en orden ascendente (R9).

    Args:
        params: Trained Dixon-Coles parameters from load_params.
        home_code: FIFA code of the home team.
        away_code: FIFA code of the away team.
        total_lines: Tuple of k+0.5 lines for total goals market.
        team_lines: Tuple of k+0.5 lines for per-team goals market.

    Returns:
        MarketSummary with all market probabilities.

    Raises:
        UnknownTeamError: If home_code or away_code is not in the trained params.
    """
    # Una sola llamada a predict_match (R5); UnknownTeamError se propaga
    pred = predict_match(params, home_code, away_code)
    matrix = pred.matrix

    # Ordenar lineas ascendentemente (R9)
    sorted_total = tuple(sorted(total_lines))
    sorted_team = tuple(sorted(team_lines))

    # Over/under para goles totales (R2)
    totals = tuple(
        MarketLine(
            line=ln,
            over=prob_over(matrix, ln),
            under=1.0 - prob_over(matrix, ln),
        )
        for ln in sorted_total
    )

    # BTTS (R3)
    btts_yes = prob_btts(matrix)
    btts_no = 1.0 - btts_yes

    # Totales por equipo (R4)
    home_totals = tuple(
        MarketLine(
            line=ln,
            over=prob_team_over(matrix, "home", ln),
            under=1.0 - prob_team_over(matrix, "home", ln),
        )
        for ln in sorted_team
    )
    away_totals = tuple(
        MarketLine(
            line=ln,
            over=prob_team_over(matrix, "away", ln),
            under=1.0 - prob_team_over(matrix, "away", ln),
        )
        for ln in sorted_team
    )

    return MarketSummary(
        home_code=home_code,
        away_code=away_code,
        prob_home=float(pred.prob_home),
        prob_draw=float(pred.prob_draw),
        prob_away=float(pred.prob_away),
        totals=totals,
        btts_yes=float(btts_yes),
        btts_no=float(btts_no),
        home_totals=home_totals,
        away_totals=away_totals,
    )
