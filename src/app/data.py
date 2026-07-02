"""Capa de datos pura del paquete src/app (R1–R7, R9–R12).

Carga y validacion de insumos del pipeline (gold/bronze), clasificacion de partidos
WC2026 sin reloj, predicciones con el modelo real y fichas de equipo.

Sin streamlit ni modulos de red: importar este modulo no dispara lecturas de disco,
conexiones de red ni escritura de archivos (R4, R13).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..ingestion.public_data import to_fifa_code
from ..ingestion.teams import all_teams, is_host
from ..models.dixon_coles import (
    DixonColesParams,
    MatchPrediction,
    NotFittedError,
    UnknownTeamError,
    load_params,
    predict_match,
)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constantes de rutas por defecto (R1)
# ---------------------------------------------------------------------------

DEFAULT_FEATURES_CSV = Path("data/gold/team_features.csv")
DEFAULT_ELO_HISTORY_CSV = Path("data/gold/elo_history.csv")
DEFAULT_PARAMS_PATH = Path("data/gold/dixon_coles_params.json")
DEFAULT_RESULTS_CSV = Path("data/bronze/public_results/results.csv")

# Literal del torneo (mismo criterio que schedule en src/cli.py y feature 8)
WC_TOURNAMENT = "FIFA World Cup"

# Fecha minima (inclusive) para filtrar partidos de la edicion WC2026 (R5).
# Comparacion lexicografica ISO: excluye todas las ediciones anteriores al Mundial 2026.
WC2026_FROM_DATE = "2026-01-01"

# Conjunto de codigos de las 48 selecciones para filtros rapidos
_WC_CODES: frozenset[str] = frozenset(t.code for t in all_teams())


# ---------------------------------------------------------------------------
# Excepciones (R2)
# ---------------------------------------------------------------------------


class AppInputError(Exception):
    """Insumo critico ausente o invalido; mensaje incluye ruta y comando del pipeline (R2)."""


# ---------------------------------------------------------------------------
# Modelo de datos (R4, R5, R7, R10)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WcMatch:
    """Partido del Mundial 2026 extraido del CSV bronze (R5).

    Args:
        date: Fecha ISO YYYY-MM-DD.
        home_name: Nombre del equipo local (dataset).
        away_name: Nombre del equipo visitante (dataset).
        home_code: Codigo FIFA del local; None si to_fifa_code no resuelve.
        away_code: Codigo FIFA del visitante; None si to_fifa_code no resuelve.
        home_score: Goles del local (jugado); None si pendiente.
        away_score: Goles del visitante (jugado); None si pendiente.
        played: True si ambos scores son int convertibles.
        predecible: True si home_code y away_code estan disponibles.
    """

    date: str
    home_name: str
    away_name: str
    home_code: str | None
    away_code: str | None
    home_score: int | None
    away_score: int | None
    played: bool
    predecible: bool


@dataclass(frozen=True)
class OutcomeEval:
    """Evaluacion del desenlace real vs prediccion del modelo (R7).

    Args:
        outcome: Desenlace real: '1' (local), 'X' (empate), '2' (visitante).
        prob_outcome: Probabilidad asignada al desenlace real por el modelo.
        acierto: True si el desenlace real fue el mas probable (desempate: orden 1,X,2).
    """

    outcome: str  # '1', 'X' o '2'
    prob_outcome: float
    acierto: bool


@dataclass(frozen=True)
class TeamProfile:
    """Ficha de una seleccion (R10).

    Args:
        code: Codigo FIFA.
        elo: Elo actual (de team_features).
        matches_count: Numero de partidos en la ventana de features.
        gf_ma15: Media movil de goles a favor; None si matches_count=0.
        ga_ma15: Media movil de goles en contra; None si matches_count=0.
        attack: Fuerza ofensiva del modelo (None si el equipo no esta en params).
        defense: Fuerza defensiva del modelo (None si el equipo no esta en params).
        history_rows: Filas del historial Elo del equipo (lista de dict).
        matches: Partidos WC2026 del equipo (local o visitante).
    """

    code: str
    elo: float | None
    matches_count: int
    gf_ma15: float | None
    ga_ma15: float | None
    attack: float | None
    defense: float | None
    history_rows: tuple[dict, ...]
    matches: tuple[WcMatch, ...]


@dataclass(frozen=True)
class AppData:
    """Estado cargado de la aplicacion a partir de los insumos del pipeline (R1).

    Args:
        features_rows: Filas del CSV team_features (lista de dict de strings).
        history_rows: Filas del CSV elo_history (lista de dict de strings).
        params: Parametros Dixon-Coles cargados con load_params.
        matches: Partidos WC2026 clasificados (jugado/pendiente) sin reloj.
        bronze_disponible: False si results.csv no existe (degradacion R3).
    """

    features_rows: tuple[dict, ...]
    history_rows: tuple[dict, ...]
    params: DixonColesParams
    matches: tuple[WcMatch, ...]
    bronze_disponible: bool


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------


def _is_int(value: str | None) -> bool:
    """Criterio jugado/pendiente sin reloj: True si value es convertible a int (R5).

    Identico al criterio de schedule en src/cli.py y feature 8.
    """
    if value is None:
        return False
    try:
        int(value)
        return True
    except (ValueError, TypeError):
        return False


def _load_csv(path: Path) -> list[dict]:
    """Lee un CSV con csv.DictReader; celdas vacias como cadena vacia (stdlib, R4)."""
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _parse_wc_matches(results_csv: Path) -> list[WcMatch]:
    """Parsea el CSV bronze y devuelve partidos WC2026 clasificados sin reloj (R5).

    Filas malformadas/incompletas se ignoran de forma defensiva.
    Orden ascendente (date, home_team, away_team) (R5).
    """
    matches: list[WcMatch] = []
    try:
        with results_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    tournament = row.get("tournament", "")
                    if tournament != WC_TOURNAMENT:
                        continue
                    date_val = row.get("date", "")
                    if not date_val or date_val < WC2026_FROM_DATE:
                        continue
                    home_name = row.get("home_team", "")
                    away_name = row.get("away_team", "")
                    if not home_name or not away_name:
                        continue

                    hs = row.get("home_score", "")
                    as_ = row.get("away_score", "")
                    played = _is_int(hs) and _is_int(as_)
                    home_score = int(hs) if played else None
                    away_score = int(as_) if played else None

                    home_code = to_fifa_code(home_name)
                    away_code = to_fifa_code(away_name)
                    predecible = home_code is not None and away_code is not None

                    matches.append(
                        WcMatch(
                            date=date_val,
                            home_name=home_name,
                            away_name=away_name,
                            home_code=home_code,
                            away_code=away_code,
                            home_score=home_score,
                            away_score=away_score,
                            played=played,
                            predecible=predecible,
                        )
                    )
                except (KeyError, TypeError):
                    continue
    except OSError:
        return []

    matches.sort(key=lambda m: (m.date, m.home_name, m.away_name))
    return matches


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------


def load_app_data(
    features_csv: Path | str = DEFAULT_FEATURES_CSV,
    elo_history_csv: Path | str = DEFAULT_ELO_HISTORY_CSV,
    params_path: Path | str = DEFAULT_PARAMS_PATH,
    results_csv: Path | str = DEFAULT_RESULTS_CSV,
) -> AppData:
    """Carga y valida todos los insumos del pipeline (R1).

    Orden de validacion: gold → params → bronze (el bronze es el unico opcional).

    Args:
        features_csv: Ruta a data/gold/team_features.csv.
        elo_history_csv: Ruta a data/gold/elo_history.csv.
        params_path: Ruta a data/gold/dixon_coles_params.json.
        results_csv: Ruta a data/bronze/public_results/results.csv.

    Returns:
        AppData con todo el estado cargado.

    Raises:
        AppInputError: Si falta features.csv, elo_history.csv o params invalidos (R2).
    """
    features_path = Path(features_csv)
    history_path = Path(elo_history_csv)
    params_p = Path(params_path)
    results_p = Path(results_csv)

    # Validacion gold (R2)
    if not features_path.is_file():
        raise AppInputError(
            f"Falta el archivo de features: {features_path}. "
            f"Ejecuta primero build-features: "
            f"python -m src.features.build --as-of-date YYYY-MM-DD"
        )
    if not history_path.is_file():
        raise AppInputError(
            f"Falta el historial Elo: {history_path}. "
            f"Ejecuta primero build-features: "
            f"python -m src.features.build --as-of-date YYYY-MM-DD"
        )

    features_rows = tuple(_load_csv(features_path))
    history_rows = tuple(_load_csv(history_path))

    # Validacion params (R2)
    try:
        params = load_params(params_p)
    except NotFittedError as exc:
        raise AppInputError(
            f"Parametros del modelo no disponibles o invalidos ({exc}). "
            f"Ejecuta primero train: "
            f"python -m src.models.dixon_coles --as-of-date YYYY-MM-DD"
        ) from exc

    # Bronze opcional (R3)
    if results_p.is_file():
        matches = tuple(_parse_wc_matches(results_p))
        bronze_disponible = True
    else:
        matches = ()
        bronze_disponible = False

    return AppData(
        features_rows=features_rows,
        history_rows=history_rows,
        params=params,
        matches=matches,
        bronze_disponible=bronze_disponible,
    )


def pending_default_day(matches: tuple[WcMatch, ...]) -> str | None:
    """Dia seleccionado por defecto en la tira de dias (R5).

    Devuelve el primer dia (orden cronologico) con >= 1 partido pendiente.
    Si no hay pendientes, el ultimo dia con partidos.
    Si no hay partidos, None.

    Pura, sin reloj.

    Args:
        matches: Tupla de WcMatch ordenada cronologicamente.

    Returns:
        Fecha ISO YYYY-MM-DD o None.
    """
    pendientes = [m.date for m in matches if not m.played]
    if pendientes:
        return min(pendientes)

    todos = [m.date for m in matches]
    if todos:
        return max(todos)

    return None


def predict_for(match: WcMatch, params: DixonColesParams) -> MatchPrediction | None:
    """Prediccion 1X2 real para un partido (R6).

    Llama a predict_match con los parametros cargados (sin reentrenar).
    Devuelve None si el partido no es predecible o surge UnknownTeamError.

    Args:
        match: Partido con home_code y away_code.
        params: Parametros Dixon-Coles cargados.

    Returns:
        MatchPrediction o None.
    """
    if not match.predecible or match.home_code is None or match.away_code is None:
        return None
    try:
        return predict_match(params, match.home_code, match.away_code)
    except UnknownTeamError:
        return None


def match_outcome_eval(match: WcMatch, pred: MatchPrediction) -> OutcomeEval:
    """Evaluacion del desenlace real vs prediccion del modelo para un partido jugado (R7).

    El desenlace real se determina por los scores del partido.
    El acierto usa desempate determinista: orden (1, X, 2).

    Args:
        match: Partido jugado (played=True) con home_score y away_score.
        pred: Prediccion del modelo para ese partido.

    Returns:
        OutcomeEval con outcome, prob_outcome y acierto.
    """
    hs = match.home_score if match.home_score is not None else 0
    as_ = match.away_score if match.away_score is not None else 0

    if hs > as_:
        outcome = "1"
    elif hs == as_:
        outcome = "X"
    else:
        outcome = "2"

    prob_map = {"1": pred.prob_home, "X": pred.prob_draw, "2": pred.prob_away}
    prob_outcome = prob_map[outcome]

    # Argmax con desempate determinista por orden (1, X, 2)
    order = ["1", "X", "2"]
    best = max(order, key=lambda k: (prob_map[k], -order.index(k)))
    acierto = outcome == best

    return OutcomeEval(outcome=outcome, prob_outcome=prob_outcome, acierto=acierto)


def team_profile(code: str, app_data: AppData) -> TeamProfile:
    """Ficha de una seleccion (R10).

    Recupera elo actual, forma, fuerzas y partidos WC2026 del equipo.
    Si el equipo no tiene historial o forma (matches_count=0), lo indica sin fallar.

    Args:
        code: Codigo FIFA de la seleccion.
        app_data: Estado cargado de la aplicacion.

    Returns:
        TeamProfile con todos los campos disponibles.
    """
    # features del equipo
    feat_row = next((r for r in app_data.features_rows if r.get("code") == code), None)

    elo: float | None = None
    matches_count = 0
    gf_ma15: float | None = None
    ga_ma15: float | None = None

    if feat_row is not None:
        try:
            elo = float(feat_row.get("elo", "") or 0)
        except (ValueError, TypeError):
            elo = None

        try:
            matches_count = int(feat_row.get("matches_count", "0") or "0")
        except (ValueError, TypeError):
            matches_count = 0

        if matches_count > 0:
            try:
                gf_raw = feat_row.get("gf_ma15", "")
                gf_ma15 = float(gf_raw) if gf_raw else None
            except (ValueError, TypeError):
                gf_ma15 = None
            try:
                ga_raw = feat_row.get("ga_ma15", "")
                ga_ma15 = float(ga_raw) if ga_raw else None
            except (ValueError, TypeError):
                ga_ma15 = None

    # fuerzas del modelo
    attack = app_data.params.attack.get(code)
    defense = app_data.params.defense.get(code)

    # historial Elo del equipo
    hist = tuple(r for r in app_data.history_rows if r.get("code") == code)

    # partidos WC2026 donde el equipo participa
    team_matches = tuple(
        m for m in app_data.matches
        if m.home_code == code or m.away_code == code
    )

    return TeamProfile(
        code=code,
        elo=elo,
        matches_count=matches_count,
        gf_ma15=gf_ma15,
        ga_ma15=ga_ma15,
        attack=attack,
        defense=defense,
        history_rows=hist,
        matches=team_matches,
    )
