"""Sub-modelo Elo → 1X2 y artefacto gold de Elo externo (Feature 14, R3, R4, R7).

Convierte la diferencia de Elo entre dos equipos en probabilidades 1X2 mediante
la fórmula estándar de expected score más un parámetro de empate ``d``:

    expected_score = 1 / (1 + 10^(−(ΔElo + H) / 400))

donde:
- ``ΔElo = elo_home − elo_away``
- ``H``: ventaja de localía en puntos Elo (default 100); 0 si ``neutral=True``
- ``expected_score`` ∈ (0, 1): probabilidad de que el local "gane" en términos Elo

Conversión a 1X2 con parámetro de empate ``d`` (R4):
    p_draw  = d · (1 − |2·E − 1|)    banda de empate proporcional al equilibrio
    p_rest  = 1 − p_draw
    p_home  = E · p_rest / (E · p_rest + (1−E) · p_rest)  →  simplificado:
    p_home  = E · (1 − p_draw)  /  (E + (1−E))           pero renormalizando:

Fórmula exacta implementada:
    raw_home = E · (1 − p_draw)
    raw_away = (1 − E) · (1 − p_draw)
    p_draw   = d · (1 − |2·E − 1|)
    # Renormalizar los tres para que sumen 1:
    total = raw_home + p_draw + raw_away   # = 1 por construcción; se renormaliza
    p_home = raw_home / total
    p_draw = p_draw  / total
    p_away = raw_away / total

Fuente de Elo (R7 — anti-fuga):
- En backtest: usar ``elo_history`` con valor as-of (``date < fecha_partido``),
  leak-free. El código IMPIDE usar el Elo externo (snapshot) en rutas de backtest
  levantando :class:`EloExternoEnBacktestError`.
- En predicción live: opcionalmente usar el Elo externo de eloratings (snapshot).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from ..features.elo import ratings_as_of

# Parámetros inyectables (R4)
DEFAULT_HOME_ADVANTAGE = 100.0   # ventaja de localía en puntos Elo
DEFAULT_DRAW_PARAM = 0.3         # parámetro d; calibrado junto con w en R6
DEFAULT_ELO_SCALE = 400.0        # escala de la fórmula estándar eloratings.net

DEFAULT_GOLD_ELO_HISTORY = Path("data/gold/elo_history.csv")
DEFAULT_GOLD_EXTERNAL_ELO = Path("data/gold/external_elo.csv")


class EloExternoEnBacktestError(RuntimeError):
    """Se intentó usar el Elo externo (snapshot eloratings) en una ruta de backtest (R7).

    El Elo externo es un snapshot actual sin series históricas; usarlo en backtest
    histórico introduce fuga temporal. Este error impide ese uso en el código.
    """


class EloProbs(NamedTuple):
    """Probabilidades 1X2 producidas por el sub-modelo Elo (R4)."""

    prob_home: float
    prob_draw: float
    prob_away: float


@dataclass(frozen=True)
class EloModelParams:
    """Parámetros inyectables del sub-modelo Elo→1X2 (R4).

    Attributes:
        home_advantage: Home field advantage in Elo points (default 100).
            Set to 0 for neutral venues.
        draw_param: Draw probability bandwidth ``d`` (R4, calibrated in R6).
        elo_scale: Denominator scale of the Elo formula (default 400).
    """

    home_advantage: float = DEFAULT_HOME_ADVANTAGE
    draw_param: float = DEFAULT_DRAW_PARAM
    elo_scale: float = DEFAULT_ELO_SCALE


def expected_score(
    elo_home: float,
    elo_away: float,
    neutral: bool,
    params: EloModelParams | None = None,
) -> float:
    """Calcula el expected score del local según la fórmula Elo estándar (R4).

    ``E = 1 / (1 + 10^(−(ΔElo + H) / scale))``

    donde ``H = home_advantage`` si ``not neutral`` else 0.

    Args:
        elo_home: Elo rating of the home team.
        elo_away: Elo rating of the away team.
        neutral: If True, no home advantage is applied.
        params: Elo model parameters (injected; default if None).

    Returns:
        Expected score in (0, 1) — probability of home "winning" in Elo terms.
    """
    p = params or EloModelParams()
    h = 0.0 if neutral else p.home_advantage
    delta_elo = elo_home - elo_away + h
    return 1.0 / (1.0 + 10.0 ** (-delta_elo / p.elo_scale))


def elo_to_1x2(
    elo_home: float,
    elo_away: float,
    neutral: bool,
    params: EloModelParams | None = None,
) -> EloProbs:
    """Convierte ratings Elo a probabilidades 1X2 (R4).

    Fórmula documentada:
        E = expected_score(elo_home, elo_away, neutral, params)
        p_draw_raw  = d · (1 − |2·E − 1|)      # banda de empate
        p_home_raw  = E · (1 − p_draw_raw)
        p_away_raw  = (1−E) · (1 − p_draw_raw)
        total       = p_home_raw + p_draw_raw + p_away_raw  # ≈ 1 por construcción
        p_home = p_home_raw / total              # renormalización exacta
        p_draw = p_draw_raw / total
        p_away = p_away_raw / total

    El parámetro ``d`` controla la anchura de la banda de empate:
    - d=0: solo victoria/derrota (nunca draw).
    - d>0: equipos equilibrados (E≈0.5) tienen mayor p_draw.

    Args:
        elo_home: Elo rating of the home team.
        elo_away: Elo rating of the away team.
        neutral: If True, no home advantage is applied.
        params: Elo model parameters (injected; default if None).

    Returns:
        EloProbs with (prob_home, prob_draw, prob_away) summing to 1.
    """
    p = params or EloModelParams()
    e = expected_score(elo_home, elo_away, neutral, params)
    # Banda de empate: máxima cuando los equipos son iguales (E=0.5)
    p_draw_raw = p.draw_param * (1.0 - abs(2.0 * e - 1.0))
    p_home_raw = e * (1.0 - p_draw_raw)
    p_away_raw = (1.0 - e) * (1.0 - p_draw_raw)
    total = p_home_raw + p_draw_raw + p_away_raw
    return EloProbs(
        prob_home=p_home_raw / total,
        prob_draw=p_draw_raw / total,
        prob_away=p_away_raw / total,
    )


def elo_from_history(
    team_code: str,
    as_of_date: str,
    history: pd.DataFrame,
    initial: float = 1500.0,
) -> float:
    """Devuelve el rating Elo as-of desde ``elo_history`` (leak-free, R7).

    Usa solo partidos con ``date < as_of_date`` (exclusión estricta anti-fuga).
    Si el equipo no tiene historial devuelve ``initial``.

    Args:
        team_code: FIFA 3-letter code of the team.
        as_of_date: Date cutoff YYYY-MM-DD; only rows with date < this are used.
        history: DataFrame with elo_history schema (columns: date, code, elo_post, …).
        initial: Default Elo rating if team has no prior history.

    Returns:
        Elo rating as float.
    """
    ratings = ratings_as_of(history, as_of_date)
    return ratings.get(team_code, initial)


def elo_from_external(
    team_code: str,
    external_elo_path: Path | str = DEFAULT_GOLD_EXTERNAL_ELO,
    initial: float = 1500.0,
    _allow_in_backtest: bool = False,
) -> float:
    """Devuelve el rating Elo externo (snapshot eloratings.net) para un equipo (R7).

    SOLO para predicción live. En backtest debe llamarse con
    ``_allow_in_backtest=False`` (default); si se intenta con False y no hay
    un indicador explícito, el código simplemente NO está en la ruta de backtest.
    Para prevenir uso accidental en rutas de backtest, la función de ensemble
    ``ensemble_from_params`` tiene su propio guard (R7).

    Args:
        team_code: FIFA 3-letter code of the team.
        external_elo_path: Path to gold external_elo.csv.
        initial: Default Elo rating if team not found.
        _allow_in_backtest: Internal flag; if False (default), safe for live use.

    Returns:
        Elo rating as float.
    """
    path = Path(external_elo_path)
    if not path.is_file():
        return initial
    df = pd.read_csv(path)
    if "team_code" not in df.columns or "elo" not in df.columns:
        return initial
    row = df[df["team_code"] == team_code]
    if row.empty:
        return initial
    return float(row["elo"].iloc[-1])


def predict_elo(
    home_code: str,
    away_code: str,
    as_of_date: str,
    history: pd.DataFrame,
    neutral: bool = False,
    params: EloModelParams | None = None,
    initial: float = 1500.0,
) -> EloProbs:
    """Predicción 1X2 desde elo_history as-of (leak-free, para backtest y live) (R4, R7).

    Fuente de Elo: ``elo_history`` con valor ``date < as_of_date`` (anti-fuga).
    Esta función es segura para backtest porque solo usa el historial propio (R7).

    Args:
        home_code: FIFA code of the home team.
        away_code: FIFA code of the away team.
        as_of_date: Date cutoff YYYY-MM-DD (anti-leakage gate).
        history: elo_history DataFrame.
        neutral: If True, no home advantage.
        params: Elo model parameters.
        initial: Default Elo rating for teams without history.

    Returns:
        EloProbs with 1X2 probabilities.
    """
    elo_home = elo_from_history(home_code, as_of_date, history, initial)
    elo_away = elo_from_history(away_code, as_of_date, history, initial)
    return elo_to_1x2(elo_home, elo_away, neutral, params)


def predict_elo_live(
    home_code: str,
    away_code: str,
    neutral: bool = False,
    params: EloModelParams | None = None,
    external_elo_path: Path | str = DEFAULT_GOLD_EXTERNAL_ELO,
    initial: float = 1500.0,
) -> EloProbs:
    """Predicción 1X2 desde Elo externo (snapshot, SOLO para live, NUNCA backtest) (R7).

    Usa ``external_elo.csv`` (snapshot eloratings.net). Prohibido en backtest
    histórico por fuga temporal (eloratings solo publica el snapshot actual).

    Args:
        home_code: FIFA code of the home team.
        away_code: FIFA code of the away team.
        neutral: If True, no home advantage.
        params: Elo model parameters.
        external_elo_path: Path to gold external_elo.csv.
        initial: Default Elo rating if team not found.

    Returns:
        EloProbs with 1X2 probabilities.
    """
    elo_home = elo_from_external(home_code, external_elo_path, initial)
    elo_away = elo_from_external(away_code, external_elo_path, initial)
    return elo_to_1x2(elo_home, elo_away, neutral, params)


def predict_elo_backtest(
    home_code: str,
    away_code: str,
    as_of_date: str,
    history: pd.DataFrame,
    neutral: bool = False,
    params: EloModelParams | None = None,
    initial: float = 1500.0,
    use_external: bool = False,
) -> EloProbs:
    """Predicción 1X2 para rutas de backtest (R7 — anti-fuga obligatoria).

    Si ``use_external=True`` → levanta :class:`EloExternoEnBacktestError` (R7).
    Solo ``elo_history`` as-of es válido en backtest.

    Args:
        home_code: FIFA code of the home team.
        away_code: FIFA code of the away team.
        as_of_date: Date cutoff YYYY-MM-DD.
        history: elo_history DataFrame (leak-free).
        neutral: If True, no home advantage.
        params: Elo model parameters.
        initial: Default Elo rating.
        use_external: If True, raises EloExternoEnBacktestError (R7 guard).

    Returns:
        EloProbs from elo_history as-of.

    Raises:
        EloExternoEnBacktestError: If use_external=True is passed.
    """
    if use_external:
        raise EloExternoEnBacktestError(
            "El Elo externo (eloratings snapshot) NO puede usarse en backtest histórico: "
            "introduce fuga temporal. Usa elo_history as-of (date < fecha_partido). "
            "Documentado en design.md de la feature 14 (R7)."
        )
    return predict_elo(
        home_code, away_code, as_of_date, history, neutral, params, initial
    )
