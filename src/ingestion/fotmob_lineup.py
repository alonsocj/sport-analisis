"""src/ingestion/fotmob_lineup.py — Alineaciones (XI) + ratings desde fotmob (Feature 28).

Parsea ``content.lineup`` de una página de partido de fotmob (vía transporte INYECTABLE),
extrae por equipo los titulares con ``performance.seasonRating`` (disponible pre-partido) y
``performance.rating`` (del partido, null antes de jugarse), y persiste bronze
``data/bronze/lineups/<slug>.json`` + sidecar meta.

Reutiliza el bracket de F27 (``fetch_bracket``) para descubrir las URLs de partido. Regla
STOP: ejecutar con transporte real requiere aprobación previa.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

from .fotmob_stats import (
    DEFAULT_RATE_LIMIT_SECONDS,
    DEFAULT_USER_AGENT,
    _default_transport,
    _extract_next_data,
    _fotmob_stats_to_fifa_code,
    _utc_to_date,
)
from .fotmob_ko import fetch_bracket
from .roster import MatchRef

DEFAULT_BRONZE_DIR = Path("data") / "bronze" / "lineups"
LineupTransport = Callable[[str], str]


@dataclass
class PlayerXI:
    """Un jugador de la alineación (Feature 28, R1; ampliado F31-R1)."""

    name: str
    position_id: int | None
    usual_position_id: int | None
    is_starter: bool
    match_rating: float | None
    season_rating: float | None
    # F31-R1: campos para el "jugador destacado". market_value tiene cobertura 100%
    # (incluso XI predicho), a diferencia de season_rating (esparso).
    market_value: int | None = None
    shirt_number: int | None = None
    club: str | None = None
    age: int | None = None


@dataclass
class RawLineup:
    """Alineación cruda de un partido (Feature 28, R1)."""

    match_ref: MatchRef
    has_lineup: bool
    lineup_type: str = ""
    date: str = ""
    home_name: str = ""
    away_name: str = ""
    home_code: str | None = None
    away_code: str | None = None
    home: list[PlayerXI] = field(default_factory=list)
    away: list[PlayerXI] = field(default_factory=list)


def _to_float(v: Any) -> float | None:
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _parse_players(team_data: dict) -> list[PlayerXI]:
    """Extrae los titulares (``starters``) de un equipo de ``content.lineup``."""
    players: list[PlayerXI] = []
    for p in team_data.get("starters", []) or []:
        if not isinstance(p, dict):
            continue
        perf = p.get("performance") or {}
        club = p.get("primaryTeamName")
        players.append(
            PlayerXI(
                name=str(p.get("name") or ""),
                position_id=_to_int(p.get("positionId")),
                usual_position_id=_to_int(p.get("usualPlayingPositionId")),
                is_starter=True,
                match_rating=_to_float(perf.get("rating")),
                season_rating=_to_float(perf.get("seasonRating")),
                market_value=_to_int(p.get("marketValue")),
                shirt_number=_to_int(p.get("shirtNumber")),
                club=str(club) if club else None,
                age=_to_int(p.get("age")),
            )
        )
    return players


def parse_match_lineup(html: str) -> dict[str, Any]:
    """Parsea ``content.lineup`` de una página de partido (R1).

    Returns:
        Dict ``lineup_type``, ``date``, ``home_name``/``away_name``, ``home``/``away``
        (listas de ``PlayerXI``). ``home``/``away`` vacías si no hay lineup.
    """
    data = _extract_next_data(html)
    page_props = (data.get("props") or {}).get("pageProps", {})
    general = page_props.get("general") or {}
    date = _utc_to_date(general.get("matchTimeUTC") or general.get("matchTime") or "")

    lineup = (page_props.get("content") or {}).get("lineup") or {}
    home_team = lineup.get("homeTeam") or {}
    away_team = lineup.get("awayTeam") or {}

    return {
        "lineup_type": str(lineup.get("lineupType") or ""),
        "date": date,
        "home_name": str(home_team.get("name") or (general.get("homeTeam") or {}).get("name") or ""),
        "away_name": str(away_team.get("name") or (general.get("awayTeam") or {}).get("name") or ""),
        "home": _parse_players(home_team),
        "away": _parse_players(away_team),
    }


def _slug_from_ref(match_ref: MatchRef) -> str:
    return match_ref.page_url.split("#")[0].rsplit("/", 1)[-1]


def _write_bronze(raw: RawLineup, url: str, fetched_at: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug_from_ref(raw.match_ref)
    doc = {
        "match_id": raw.match_ref.match_id,
        "page_url": raw.match_ref.page_url,
        "date": raw.date,
        "lineup_type": raw.lineup_type,
        "has_lineup": raw.has_lineup,
        "home_name": raw.home_name,
        "away_name": raw.away_name,
        "home_code": raw.home_code,
        "away_code": raw.away_code,
        "home": [asdict(p) for p in raw.home],
        "away": [asdict(p) for p in raw.away],
    }
    raw_bytes = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    (out_dir / f"{slug}.json").write_bytes(raw_bytes)
    meta = {
        "url": url,
        "fetched_at": fetched_at,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "match_id": raw.match_ref.match_id,
        "lineup_type": raw.lineup_type,
        "has_lineup": raw.has_lineup,
    }
    (out_dir / f"{slug}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_and_persist_lineup(
    transport: LineupTransport,
    match_ref: MatchRef,
    fetched_at: str,
    out_dir: Path = DEFAULT_BRONZE_DIR,
    *,
    sleeper: Callable[[float], None] | None = None,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
) -> RawLineup:
    """Descarga y persiste la alineación de un partido (R1, R2). Degrada si no hay lineup."""
    from .fotmob_stats import FOTMOB_BASE_URL  # noqa: PLC0415

    url = FOTMOB_BASE_URL + match_ref.page_url.split("#")[0]
    if sleeper is not None:
        sleeper(rate_limit_seconds)

    raw = RawLineup(match_ref=match_ref, has_lineup=False,
                    home_name=match_ref.home_team, away_name=match_ref.away_team,
                    date=match_ref.date)
    try:
        html = transport(url)
        parsed = parse_match_lineup(html)
        raw.lineup_type = parsed["lineup_type"]
        raw.date = parsed["date"] or match_ref.date
        raw.home_name = parsed["home_name"] or raw.home_name
        raw.away_name = parsed["away_name"] or raw.away_name
        raw.home = parsed["home"]
        raw.away = parsed["away"]
        raw.has_lineup = bool(raw.home or raw.away)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"Sin lineup para {url}: {exc}", UserWarning, stacklevel=2)

    raw.home_code = _fotmob_stats_to_fifa_code(raw.home_name)
    raw.away_code = _fotmob_stats_to_fifa_code(raw.away_name)
    _write_bronze(raw, url, fetched_at, Path(out_dir))
    return raw


@dataclass
class LineupIngestResult:
    n_matches: int
    n_with_lineup: int


def ingest_lineups(
    fetched_at: str,
    league_id: int = 77,
    transport: LineupTransport | None = None,
    bronze_dir: Path | str = DEFAULT_BRONZE_DIR,
    user_agent: str = DEFAULT_USER_AGENT,
    sleeper: Callable[[float], None] | None = None,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
) -> LineupIngestResult:
    """Scrape de alineaciones de los partidos del bracket con URL de partido (R1/R2).

    Cubre KO jugados (XI confirmado) y por jugar (XI predicho). Con ``transport=None`` usa
    el transporte real (regla STOP).
    """
    _transport = transport if transport is not None else _default_transport(user_agent)
    bracket = fetch_bracket(_transport, league_id=league_id)
    targets = [km for km in bracket if km.slug and km.page_url]
    n_with = 0
    for km in targets:
        ref = MatchRef(match_id=km.match_id, page_url=km.page_url,
                       home_team=km.home_name, away_team=km.away_name, date=km.date)
        raw = fetch_and_persist_lineup(
            _transport, ref, fetched_at, out_dir=Path(bronze_dir),
            sleeper=sleeper, rate_limit_seconds=rate_limit_seconds,
        )
        n_with += 1 if raw.has_lineup else 0
    return LineupIngestResult(n_matches=len(targets), n_with_lineup=n_with)
