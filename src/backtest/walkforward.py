"""src/backtest/walkforward.py — Walk-forward sin reloj para backtesting Dixon-Coles (R1–R3).

Genera ventanas de evaluación cronológicas consecutivas dentro de un rango
parametrizable [from_date, to_date], hace refits reales por ventana y devuelve
predicciones 1X2. Sin reloj del sistema: todas las fechas vienen del dataset o
de los argumentos (R1). El filtro de entrenamiento usa ``date < as_of_date``
(fecha de inicio de cada ventana) para garantizar exclusión estricta (R2).
Los partidos con equipos fuera del recorte del refit se omiten como ``skipped``
sin abortar (R3).
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator

import pandas as pd

from ..models.dixon_coles import (
    DCConfig,
    SilverNotFoundError,
    UnknownTeamError,
    fit_dixon_coles,
    load_training_data,
    predict_match,
)

DEFAULT_SILVER_PATH = Path("data/silver/matches.csv")


@dataclass(frozen=True)
class BacktestConfig:
    """Configuracion inmutable del backtest walk-forward (R1, design.md).

    Attributes:
        from_date: Start of evaluation window (YYYY-MM-DD). Default: 2024-01-01.
        to_date: End of evaluation window (YYYY-MM-DD). Default: max date of dataset.
        refit_every: Frequency of refit windows (``"month"`` or ``"week"``).
        xi: Dixon-Coles temporal decay per year.
        reg_lambda: Ridge regularization coefficient.
        min_matches: Minimum matches threshold for low_data_teams.
        bins: Number of calibration bins.
        value_threshold: Threshold for value bet detection (prob * odds > 1 + threshold).
        out_dir: Output directory for report files.
        odds_csv: Optional path to odds CSV file.
        silver_path: Path to silver matches CSV.
    """

    from_date: str = "2024-01-01"
    to_date: str | None = None
    refit_every: str = "month"  # "month" | "week"
    xi: float = 0.35
    reg_lambda: float = 0.25
    min_matches: int = 5
    bins: int = 10
    value_threshold: float = 0.05
    out_dir: Path = Path("data/reports/backtest")
    odds_csv: Path | None = None
    silver_path: Path = DEFAULT_SILVER_PATH

    def __post_init__(self) -> None:
        """Validates domain constraints on construction.

        Raises:
            ValueError: If ``refit_every`` is not ``"month"`` or ``"week"``.
        """
        _VALID_REFIT = ("month", "week")
        if self.refit_every not in _VALID_REFIT:
            raise ValueError(
                f"refit_every={self.refit_every!r} no valido; "
                f"valores permitidos: {_VALID_REFIT}"
            )


@dataclass
class SkippedMatch:
    """Partido omitido por no ser evaluable (R3).

    Attributes:
        date: Match date.
        home_code: Home team code.
        away_code: Away team code.
        reason: Human-readable reason for skipping.
    """

    date: str
    home_code: str
    away_code: str
    reason: str


@dataclass
class WindowPrediction:
    """Prediccion de un partido dentro de una ventana (R3, R4).

    Attributes:
        date: Match date.
        home_code: Home team code.
        away_code: Away team code.
        prob_home: Predicted probability of home win.
        prob_draw: Predicted probability of draw.
        prob_away: Predicted probability of away win.
        actual: Actual outcome (``"1"``, ``"X"`` or ``"2"``).
        marginal_home: Marginal baseline probability of home win in training window.
        marginal_draw: Marginal baseline probability of draw in training window.
        marginal_away: Marginal baseline probability of away win in training window.
    """

    date: str
    home_code: str
    away_code: str
    prob_home: float
    prob_draw: float
    prob_away: float
    actual: str
    marginal_home: float
    marginal_draw: float
    marginal_away: float


@dataclass
class WindowResult:
    """Resultado de una ventana de evaluacion (R1–R3).

    Attributes:
        window_start: Inclusive start date of the evaluation window.
        window_end: Exclusive end date of the evaluation window.
        predictions: List of predictions in this window.
        skipped: List of skipped matches in this window.
        n_train: Number of training matches used in the refit.
    """

    window_start: str
    window_end: str
    predictions: list[WindowPrediction] = field(default_factory=list)
    skipped: list[SkippedMatch] = field(default_factory=list)
    n_train: int = 0


def _month_start(d: date) -> date:
    """Returns the first day of the month of ``d``."""
    return d.replace(day=1)


def _next_month_start(d: date) -> date:
    """Returns the first day of the next month after ``d``."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _iso_week_monday(d: date) -> date:
    """Returns the Monday of the ISO week containing ``d``."""
    return d - pd.Timedelta(days=d.weekday())


def _next_week_monday(d: date) -> date:
    """Returns the Monday of the next ISO week after ``d``."""
    return _iso_week_monday(d) + pd.Timedelta(days=7)


def _generate_window_starts(
    from_date: date, to_date: date, refit_every: str
) -> list[date]:
    """Genera los cortes de inicio de ventana (sin reloj, R1).

    Cada inicio es un limite de mes/semana ISO calculado aritmeticamente.

    Args:
        from_date: First window start (inclusive).
        to_date: Last possible date (exclusive boundary for last window).
        refit_every: ``"month"`` or ``"week"``.

    Returns:
        Sorted list of window start dates.
    """
    starts: list[date] = []
    if refit_every == "month":
        # Align to start of the month containing from_date
        current = _month_start(from_date)
        while current < to_date:
            starts.append(current)
            current = _next_month_start(current)
    else:  # "week"
        current = _iso_week_monday(from_date)
        while current < to_date:
            starts.append(current)
            current = _next_week_monday(current)
    return starts


def _compute_effective_to_date(cfg: BacktestConfig, df: pd.DataFrame) -> date:
    """Calcula la fecha efectiva de fin (desde el dataset o de los args, sin reloj, R1).

    Args:
        cfg: Backtest configuration.
        df: Full silver dataframe.

    Returns:
        Effective to_date as a ``date`` object.
    """
    max_date = date.fromisoformat(df["date"].max())
    if cfg.to_date is not None:
        return min(date.fromisoformat(cfg.to_date), max_date)
    return max_date


def _outcome(home_goals: float, away_goals: float) -> str:
    """Convierte goles a resultado 1X2 (R4).

    Args:
        home_goals: Goals scored by home team.
        away_goals: Goals scored by away team.

    Returns:
        ``"1"`` for home win, ``"X"`` for draw, ``"2"`` for away win.
    """
    hg = int(home_goals)
    ag = int(away_goals)
    if hg > ag:
        return "1"
    if hg == ag:
        return "X"
    return "2"


def _compute_marginals(
    train_df: pd.DataFrame,
) -> tuple[float, float, float]:
    """Calcula frecuencias marginales de desenlaces en el entrenamiento (R6).

    Args:
        train_df: Training matches dataframe with home_goals / away_goals columns.

    Returns:
        Tuple of (marginal_home, marginal_draw, marginal_away) as fractions.
    """
    if train_df.empty:
        return 1 / 3, 1 / 3, 1 / 3
    outcomes = train_df.apply(
        lambda r: _outcome(r["home_goals"], r["away_goals"]), axis=1
    )
    counts = outcomes.value_counts()
    total = len(outcomes)
    return (
        float(counts.get("1", 0)) / total,
        float(counts.get("X", 0)) / total,
        float(counts.get("2", 0)) / total,
    )


def run(
    cfg: BacktestConfig,
    importance_map: dict[str, float] | None = None,
    form_factory: Callable[[str], Callable[[str, str], tuple[float, float]]] | None = None,
) -> tuple[list[WindowResult], str]:
    """Ejecuta el backtest walk-forward completo (R1–R3, R4 feature 12).

    Carga el silver una vez, genera ventanas cronologicas, hace un refit real
    por ventana y produce predicciones. No usa el reloj del sistema.

    Args:
        cfg: Backtest configuration.
        importance_map: Optional dict ``{tournament: factor}`` for importance
            weighting (R4 feature 12). ``None`` → v1 behaviour (no weighting).
        form_factory: Optional callable ``(as_of: str) → form_factor_fn``
            (Feature 16, R5). If provided, the form factor is rebuilt at each
            window step with the window start as the anti-fuga cutoff. ``None``
            → no form factor → v1 behaviour exact.

    Returns:
        Tuple of (list of WindowResult, effective_to_date as ISO string).

    Raises:
        SilverNotFoundError: If silver CSV does not exist or lacks required columns.
        ValueError: If no evaluation windows can be generated (from_date >= to_date).
    """
    # Cargar silver completo una vez (R2: los filtros por ventana son lo unico que
    # restringe los datos de entrenamiento y evaluacion; cero reloj)
    silver_path = cfg.silver_path
    if not Path(silver_path).is_file():
        raise SilverNotFoundError(
            f"No existe el silver: {silver_path}; ejecuta primero "
            "`build-features --as-of-date YYYY-MM-DD` o `ingest-public`"
        )
    df_full = pd.read_csv(silver_path)

    required = {"date", "home_code", "away_code", "home_goals", "away_goals"}
    missing = required - set(df_full.columns)
    if missing:
        raise SilverNotFoundError(
            f"Faltan columnas en {silver_path}: {', '.join(sorted(missing))}"
        )

    # Fechas efectivas: SOLO del dataset y los argumentos (R1)
    effective_to = _compute_effective_to_date(cfg, df_full)
    from_d = date.fromisoformat(cfg.from_date)

    if from_d >= effective_to:
        raise ValueError(
            f"from_date={cfg.from_date} >= to_date efectivo={effective_to.isoformat()}; "
            "no hay ventanas de evaluacion"
        )

    window_starts = _generate_window_starts(from_d, effective_to, cfg.refit_every)
    if not window_starts:
        raise ValueError(
            f"No se generaron ventanas de evaluacion con refit_every={cfg.refit_every!r} "
            f"entre {cfg.from_date} y {effective_to.isoformat()}"
        )

    # Configuracion de Dixon-Coles para cada refit
    dc_config = DCConfig(xi=cfg.xi, reg_lambda=cfg.reg_lambda, min_matches=cfg.min_matches)

    results: list[WindowResult] = []

    for i, win_start in enumerate(window_starts):
        # Determinar el fin de la ventana (inicio de la siguiente o effective_to)
        if i + 1 < len(window_starts):
            win_end = window_starts[i + 1]
        else:
            # La ultima ventana va hasta effective_to (inclusive)
            # Usamos el dia siguiente para filtro exclusivo
            win_end = effective_to + pd.Timedelta(days=1)
            win_end = win_end.date() if hasattr(win_end, "date") else win_end

        win_start_str = win_start.isoformat()
        win_end_str = win_end.isoformat()

        # Partidos de evaluacion: [win_start, win_end)
        eval_mask = (df_full["date"] >= win_start_str) & (df_full["date"] < win_end_str)
        eval_df = df_full[eval_mask].copy()

        wr = WindowResult(
            window_start=win_start_str,
            window_end=win_end_str,
        )

        if eval_df.empty:
            results.append(wr)
            continue

        # Refit real: entrenamiento con partidos ESTRICTAMENTE ANTERIORES al inicio
        # de la ventana (as_of_date = win_start_str) — el filtro en load_training_data
        # es `date < as_of_date`, garantizando exclusion estricta (R2).
        # importance_map se pasa directamente para ponderación v2 (R4 feature 12).
        try:
            params = fit_dixon_coles(
                win_start_str,
                silver_path=silver_path,
                config=dc_config,
                importance_map=importance_map,
            )
            wr.n_train = params.n_matches
        except (SilverNotFoundError, ValueError):
            # Si no hay datos de entrenamiento suficientes, marcar todos como skipped
            for _, row in eval_df.iterrows():
                wr.skipped.append(
                    SkippedMatch(
                        date=str(row["date"]),
                        home_code=str(row["home_code"]),
                        away_code=str(row["away_code"]),
                        reason="sin_datos_de_entrenamiento",
                    )
                )
            results.append(wr)
            continue

        # Calcular frecuencias marginales del entrenamiento (baseline R6)
        td = load_training_data(
            win_start_str, silver_path=silver_path, config=dc_config,
            importance_map=importance_map,
        )
        train_df_for_marginals = pd.DataFrame({
            "home_goals": td.x,
            "away_goals": td.y,
        })
        marg_home, marg_draw, marg_away = _compute_marginals(train_df_for_marginals)

        # Predecir cada partido de la ventana (R3: skipped si UnknownTeamError)
        for _, row in eval_df.iterrows():
            h_code = str(row["home_code"])
            a_code = str(row["away_code"])
            match_date = str(row["date"])

            # Feature 16: forma_reciente — factor de forma por ventana (R5)
            form_fn = form_factory(win_start_str) if form_factory is not None else None
            try:
                pred = predict_match(params, h_code, a_code, form_factor=form_fn)
            except UnknownTeamError as exc:
                wr.skipped.append(
                    SkippedMatch(
                        date=match_date,
                        home_code=h_code,
                        away_code=a_code,
                        reason=f"equipo_fuera_de_recorte: {exc}",
                    )
                )
                continue

            try:
                actual = _outcome(float(row["home_goals"]), float(row["away_goals"]))
            except (ValueError, TypeError):
                # Goles no numericos: partido no jugado o datos faltantes
                wr.skipped.append(
                    SkippedMatch(
                        date=match_date,
                        home_code=h_code,
                        away_code=a_code,
                        reason="goles_no_numericos",
                    )
                )
                continue

            wr.predictions.append(
                WindowPrediction(
                    date=match_date,
                    home_code=h_code,
                    away_code=a_code,
                    prob_home=pred.prob_home,
                    prob_draw=pred.prob_draw,
                    prob_away=pred.prob_away,
                    actual=actual,
                    marginal_home=marg_home,
                    marginal_draw=marg_draw,
                    marginal_away=marg_away,
                )
            )

        results.append(wr)

    return results, effective_to.isoformat()
