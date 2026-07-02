"""Factor de jugadores: cuotas/tasas, anytime-scorer y multiplicador de ataque (R3–R6).

Calcula, por (``team_code``, ``scorer``), los goles ponderados con decaimiento
exponencial (parámetro ξ inyectable, default ``DCConfig.xi = 0.35``) usando SOLO
eventos con ``fecha < as_of_date`` (anti-fuga; R3). Deriva:

- ``share`` = goles_ponderados_jugador / Σ_equipo (cuota de gol del jugador,
  suma por equipo ≈ 1 con tol 1e-9; R3).
- Probabilidad anytime-scorer: ``λ_jugador = share · λ_equipo``,
  ``P(marca≥1) = 1 − exp(−λ_jugador)`` (thinning de Poisson, R4).
- Multiplicador de ataque por roster: ``min(1.0, Σ share de disponibles)``; sin
  roster → exactamente 1.0 (identidad estricta, R5).
- Artefacto gold determinista ``data/gold/player_factor.csv`` (R6).

Supuesto documentado (R4): sin minutos ni alineaciones, la cuota histórica de goles
aproxima la participación ofensiva del jugador. No distingue titular/suplente ni
lesionados; eso requeriría API de formaciones (fuera de alcance de esta feature).

Sin reloj interno: ``as_of_date`` siempre inyectado por el caller (R8).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from ..models.dixon_coles import DCConfig, MatchPrediction, predict_match

# Constantes de escritura determinista (R6).
DEFAULT_GOLD_PATH = Path("data/gold/player_factor.csv")
_GOLD_COLUMNS = ("as_of_date", "team_code", "scorer", "goals_weighted", "share")

# Tolerancia de validación de suma de shares por equipo (R3).
SHARE_SUM_TOLERANCE: float = 1e-9

# Días por año para el decaimiento temporal (igual que dixon_coles.py, R3).
_DAYS_PER_YEAR: float = 365.25


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayerRate:
    """Cuota/tasa de gol de un jugador por equipo (R3).

    ``goals_weighted``: goles ponderados con decaimiento exponencial ξ;
    ``share``: fracción del total del equipo (suma ≈ 1 por equipo, tol 1e-9).
    """

    team_code: str
    scorer: str
    goals_weighted: float
    share: float


@dataclass(frozen=True)
class AnytimeScorer:
    """Probabilidad anytime-scorer de un jugador para un partido específico (R4)."""

    team_code: str
    scorer: str
    share: float
    lambda_player: float
    prob_score: float


# ---------------------------------------------------------------------------
# Cálculo del factor (R3)
# ---------------------------------------------------------------------------


def _decay_weight(event_date: str, as_of_date: str, xi: float) -> float:
    """Peso de decaimiento temporal ``exp(−ξ · Δaños)`` (R3).

    ``Δaños = (as_of - event_date).days / 365.25``. Siempre positivo ya que
    se garantiza ``event_date < as_of_date`` antes de llamar.

    Args:
        event_date: ISO date string of the goal event.
        as_of_date: ISO date string of the cutoff (exclusive).
        xi: Exponential decay parameter per year.

    Returns:
        Decay weight in (0, 1].
    """
    d_event = date.fromisoformat(event_date)
    d_as_of = date.fromisoformat(as_of_date)
    delta_years = (d_as_of - d_event).days / _DAYS_PER_YEAR
    return math.exp(-xi * delta_years)


def build_player_rates(
    events: list,  # list[GoalEvent] — import perezoso para evitar ciclos
    as_of_date: str,
    xi: float = DCConfig.xi,
) -> list[PlayerRate]:
    """Tabla de cuotas/tasas por (team_code, scorer) con anti-fuga y decaimiento (R3).

    Solo usa eventos con ``fecha < as_of_date`` (anti-fuga). La cuota de un jugador
    es ``goals_weighted / Σ_equipo goals_weighted``; las cuotas de un equipo suman
    exactamente 1 (normalización, tol 1e-9 verificable).

    Args:
        events: List of GoalEvent (from normalize.normalize_goalscorer_events).
        as_of_date: Cutoff date ISO YYYY-MM-DD (exclusive, anti-leakage).
        xi: Decay parameter per year. Default = DCConfig.xi = 0.35.

    Returns:
        List of PlayerRate sorted by (team_code, share desc, scorer).
    """
    # Acumular goles ponderados por (team_code, scorer)
    # Solo eventos estrictamente antes de as_of_date (anti-fuga)
    weighted: dict[tuple[str, str], float] = {}
    for ev in events:
        if ev.date >= as_of_date:
            continue  # anti-fuga: excluir eventos con fecha >= as_of_date
        w = _decay_weight(ev.date, as_of_date, xi)
        key = (ev.team_code, ev.scorer)
        weighted[key] = weighted.get(key, 0.0) + w

    if not weighted:
        return []

    # Suma por equipo para normalización
    team_totals: dict[str, float] = {}
    for (team_code, _), gw in weighted.items():
        team_totals[team_code] = team_totals.get(team_code, 0.0) + gw

    # Construir PlayerRate con share = goals_weighted / total_equipo
    rates: list[PlayerRate] = []
    for (team_code, scorer), gw in weighted.items():
        total = team_totals[team_code]
        share = gw / total if total > 0 else 0.0
        rates.append(PlayerRate(team_code=team_code, scorer=scorer, goals_weighted=gw, share=share))

    # Orden determinista: (team_code ASC, share DESC, scorer ASC) — R6
    rates.sort(key=lambda r: (r.team_code, -r.share, r.scorer))
    return rates


# ---------------------------------------------------------------------------
# Anytime-scorer — thinning de Poisson (R4)
# ---------------------------------------------------------------------------


def compute_anytime_scorers(
    rates: list[PlayerRate],
    lambda_team: float,
    team_code: str,
    top_k: int | None = None,
) -> list[AnytimeScorer]:
    """Probabilidades anytime-scorer para los jugadores de un equipo (R4).

    ``λ_jugador = share · λ_equipo``; ``P(marca≥1) = 1 − exp(−λ_jugador)``.
    Supuesto: sin minutos ni alineaciones, la cuota histórica aproxima la
    participación ofensiva (no distingue titular/suplente/lesionado — R4).

    Args:
        rates: Lista de PlayerRate (puede incluir varios equipos; se filtra por team_code).
        lambda_team: Expected goals for the team in the match (from Dixon-Coles).
        team_code: FIFA code of the team to compute scorers for.
        top_k: If given, return only the top-k players by prob_score. If None, return all.

    Returns:
        List of AnytimeScorer sorted by prob_score desc, then scorer asc.
    """
    team_rates = [r for r in rates if r.team_code == team_code]
    result: list[AnytimeScorer] = []
    for r in team_rates:
        lam = r.share * lambda_team
        prob = 1.0 - math.exp(-lam)
        result.append(
            AnytimeScorer(
                team_code=r.team_code,
                scorer=r.scorer,
                share=r.share,
                lambda_player=lam,
                prob_score=prob,
            )
        )
    # Orden: prob_score desc, scorer asc (desempate determinista)
    result.sort(key=lambda s: (-s.prob_score, s.scorer))
    if top_k is not None:
        result = result[:top_k]
    return result


# ---------------------------------------------------------------------------
# Multiplicador de ataque por roster (R5)
# ---------------------------------------------------------------------------


def attack_multiplier(
    rates: list[PlayerRate],
    team_code: str,
    roster: list[str] | None = None,
) -> float:
    """Multiplicador de ataque por disponibilidad de roster (R5).

    Si no se provee roster, devuelve exactamente 1.0 (identidad estricta, modelo
    intacto). Con roster, multiplica ``min(1.0, Σ share de los disponibles)``.

    Args:
        rates: Lista de PlayerRate completa.
        team_code: FIFA code of the team.
        roster: List of scorer names available. None → identity (1.0).

    Returns:
        Attack multiplier in [0, 1]. Exactly 1.0 if roster is None.
    """
    if roster is None:
        return 1.0
    team_rates = {r.scorer: r.share for r in rates if r.team_code == team_code}
    total_share = sum(team_rates.get(s, 0.0) for s in roster)
    return min(1.0, total_share)


# ---------------------------------------------------------------------------
# Artefacto gold (R6)
# ---------------------------------------------------------------------------


def _assert_under_data(path: Path) -> None:
    """Verifica que la ruta tenga 'data' como componente del path (R6).

    Args:
        path: Path to validate.

    Raises:
        ValueError: If 'data' is not a component of the path.
    """
    parts = Path(path).resolve().parts
    if "data" not in parts:
        raise ValueError(f"Escritura confinada a data/; ruta rechazada: {path}")


def save_player_factor(
    rates: list[PlayerRate],
    as_of_date: str,
    out_path: Path = DEFAULT_GOLD_PATH,
) -> Path:
    """Persiste el artefacto gold determinista de factor de jugadores (R6).

    Columnas: ``as_of_date, team_code, scorer, goals_weighted, share``.
    Orden: (team_code ASC, share DESC, scorer ASC) — misma entrada → mismo contenido
    byte a byte (determinismo garantizado).

    Args:
        rates: Lista de PlayerRate ya ordenada por (team_code, -share, scorer).
        as_of_date: Fecha de corte inyectada (no reloj).
        out_path: Ruta de escritura bajo data/ (validada).

    Returns:
        Path where the file was written.
    """
    out_path = Path(out_path)
    _assert_under_data(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_GOLD_COLUMNS)
        for r in rates:
            writer.writerow(
                [as_of_date, r.team_code, r.scorer, f"{r.goals_weighted:.10f}", f"{r.share:.10f}"]
            )
    return out_path


def load_player_factor(
    path: Path = DEFAULT_GOLD_PATH,
) -> list[PlayerRate]:
    """Carga el artefacto gold de factor de jugadores (R6).

    Args:
        path: Ruta del CSV gold player_factor.csv.

    Returns:
        List of PlayerRate.

    Raises:
        FileNotFoundError: Si el archivo no existe.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"No existe el artefacto gold de jugadores en {path}; "
            "ejecuta primero `build-features --as-of-date YYYY-MM-DD`"
        )
    rates: list[PlayerRate] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rates.append(
                PlayerRate(
                    team_code=row["team_code"],
                    scorer=row["scorer"],
                    goals_weighted=float(row["goals_weighted"]),
                    share=float(row["share"]),
                )
            )
    return rates


# ---------------------------------------------------------------------------
# Orquestador principal (R3–R6)
# ---------------------------------------------------------------------------


def build_player_factor(
    events: list,  # list[GoalEvent]
    as_of_date: str,
    xi: float = DCConfig.xi,
    out_path: Path = DEFAULT_GOLD_PATH,
) -> list[PlayerRate]:
    """Orquesta el cálculo del factor y persiste el artefacto gold (R3–R6).

    1. Calcula las cuotas/tasas con anti-fuga y decaimiento (R3).
    2. Persiste el artefacto gold determinista (R6).

    Args:
        events: Lista de GoalEvent normalizados (R2).
        as_of_date: Fecha de corte ISO YYYY-MM-DD (anti-fuga, inyectada).
        xi: Parámetro de decaimiento por año. Default = DCConfig.xi = 0.35.
        out_path: Ruta del gold (debe estar bajo data/).

    Returns:
        Lista de PlayerRate (misma que persiste en gold).
    """
    rates = build_player_rates(events, as_of_date, xi)
    save_player_factor(rates, as_of_date, out_path)
    return rates
