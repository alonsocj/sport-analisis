"""src/ingestion/fotmob_ko.py — Bracket de eliminatorias WC2026 desde fotmob (Feature 27).

Obtiene el árbol de knockouts (``props.pageProps.playoff.rounds``) de la página de
playoff de fotmob vía un transporte INYECTABLE (url → html), lo normaliza a una lista
de ``KoMatch`` (por partido: ronda, equipos, marcador, id, estado) y deriva los CSV de
fixtures ``r16_fixtures.csv`` (octavos) y ``r8_fixtures.csv`` (cuartos) para la app (F30).

Seguridad / diseño (coherente con F21/F23):
- Transporte inyectable: cero red en tests.
- Escritura sólo bajo ``data/``.
- Mapeo de nombres → código FIFA con ``_fotmob_stats_to_fifa_code``; equipos aún
  indefinidos (``"Winner QF 2"``, ``"Portugal/Spain"``) → código ``None`` (no se fuerza).
- Regla STOP de CLAUDE.md: ejecutar ``fetch_bracket`` con transporte real requiere
  aprobación previa del usuario.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .fotmob_stats import (
    DEFAULT_BRONZE_DIR as FOTMOB_STATS_BRONZE_DIR,
    DEFAULT_RATE_LIMIT_SECONDS,
    DEFAULT_USER_AGENT,
    RawMatchStats,
    _default_transport,
    _extract_next_data,
    _fotmob_stats_to_fifa_code,
    fetch_and_persist,
)
from .roster import MatchRef

FOTMOB_BASE_URL = "https://www.fotmob.com"
FOTMOB_PLAYOFF_URL_TEMPLATE = (
    "https://www.fotmob.com/leagues/{league_id}/playoff/world-cup"
)
DEFAULT_KNOCKOUTS_DIR = Path("data") / "knockouts"

# playoff.rounds[i] → etapa (índice 0-based). WC48: R32 → R16 → QF → SF → Final.
STAGES: tuple[str, ...] = ("R32", "R16", "QF", "SF", "Final")

KoTransport = Callable[[str], str]


@dataclass(frozen=True)
class KoMatch:
    """Un partido del bracket de eliminatorias (Feature 27, R1).

    Attributes:
        round_ordinal: 1=R32, 2=R16, 3=QF, 4=SF, 5=Final.
        stage: Etiqueta de etapa (``STAGES[round_ordinal-1]``).
        home_name / away_name: Nombres fotmob de los equipos (o placeholders TBD).
        home_code / away_code: Código FIFA o ``None`` si el equipo aún no está definido.
        home_goals / away_goals: Marcador (int) o ``None`` si no ha terminado.
        match_id: ID numérico de fotmob (string).
        slug: Slug del partido (para el bronze de stats).
        page_url: Ruta relativa de la página del partido en fotmob.
        utc_time / date: Fecha-hora UTC y fecha ``YYYY-MM-DD``.
        finished / started: Estado del partido.
    """

    round_ordinal: int
    stage: str
    home_name: str
    away_name: str
    home_code: str | None
    away_code: str | None
    home_goals: int | None
    away_goals: int | None
    match_id: str
    slug: str
    page_url: str
    utc_time: str
    date: str
    finished: bool
    started: bool


def _int_or_none(val: Any) -> int | None:
    """Devuelve ``val`` si es un int no-booleano, si no ``None``."""
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    return None


def _slug_and_id(page_url: str, fallback_id: str) -> tuple[str, str]:
    """Deriva ``(slug, match_id)`` de un ``pageUrl`` fotmob.

    ``/matches/france-vs-paraguay/1hu3vk#4653842`` → slug ``1hu3vk``, id ``4653842``.
    """
    if not page_url:
        return ("", str(fallback_id or ""))
    base, _, frag = page_url.partition("#")
    slug = base.rsplit("/", 1)[-1]
    match_id = frag or str(fallback_id or "")
    return (slug, match_id)


def parse_playoff_bracket(next_data: dict) -> list[KoMatch]:
    """Normaliza ``props.pageProps.playoff.rounds`` a una lista de ``KoMatch`` (R1).

    Recorre las rondas por orden (ordinal = índice+1). Cada ronda tiene ``matchups``;
    cada matchup tiene ``matches`` (lista, normalmente 1). SI una ronda no existe o no
    tiene matchups → se omite sin fallar.

    Args:
        next_data: Dict del ``__NEXT_DATA__`` de la página de playoff.

    Returns:
        Lista de ``KoMatch`` en orden de bracket.
    """
    playoff = (
        (next_data.get("props") or {}).get("pageProps", {}).get("playoff") or {}
    )
    rounds = playoff.get("rounds") or []
    out: list[KoMatch] = []

    for idx, rnd in enumerate(rounds):
        ordinal = idx + 1
        stage = STAGES[idx] if idx < len(STAGES) else f"R{ordinal}"
        matchups = rnd.get("matchups") or []
        for matchup in matchups:
            matches = matchup.get("matches")
            if not matches:
                # Algunos matchups exponen home/away directamente
                matches = [matchup] if ("home" in matchup or "away" in matchup) else []
            for mt in matches:
                home = mt.get("home") or {}
                away = mt.get("away") or {}
                home_name = str(home.get("name") or home.get("shortName") or "")
                away_name = str(away.get("name") or away.get("shortName") or "")
                status = mt.get("status") or {}
                utc_time = str(status.get("utcTime") or "")
                page_url = str(mt.get("pageUrl") or "")
                slug, match_id = _slug_and_id(
                    page_url, str(mt.get("matchId") or mt.get("id") or "")
                )
                out.append(
                    KoMatch(
                        round_ordinal=ordinal,
                        stage=stage,
                        home_name=home_name,
                        away_name=away_name,
                        home_code=_fotmob_stats_to_fifa_code(home_name),
                        away_code=_fotmob_stats_to_fifa_code(away_name),
                        home_goals=_int_or_none(home.get("score")),
                        away_goals=_int_or_none(away.get("score")),
                        match_id=match_id,
                        slug=slug,
                        page_url=page_url,
                        utc_time=utc_time,
                        date=utc_time[:10] if len(utc_time) >= 10 else "",
                        finished=bool(status.get("finished")),
                        started=bool(status.get("started")),
                    )
                )
    return out


def fetch_bracket(transport: KoTransport, league_id: int = 77) -> list[KoMatch]:
    """Descarga y parsea el bracket de eliminatorias desde fotmob (R1).

    Con transporte real (``requests``) esto hace RED — regla STOP.

    Args:
        transport: Callable url→html inyectable (sin red en tests).
        league_id: ID de la liga fotmob (default 77 = Mundial 2026).

    Returns:
        Lista de ``KoMatch``; vacía si el ``__NEXT_DATA__`` no se puede parsear.
    """
    url = FOTMOB_PLAYOFF_URL_TEMPLATE.format(league_id=league_id)
    html = transport(url)
    try:
        data = _extract_next_data(html)
    except ValueError:  # incluye json.JSONDecodeError (subclase de ValueError)
        return []
    return parse_playoff_bracket(data)


def ko_match_to_ref(km: KoMatch) -> MatchRef:
    """Construye un ``MatchRef`` para alimentar ``fetch_and_persist`` de stats (R3)."""
    return MatchRef(
        match_id=km.match_id,
        page_url=km.page_url,
        home_team=km.home_name,
        away_team=km.away_name,
        date=km.date,
    )


# Etapa (ordinal) → nombre de archivo de fixtures. Sólo octavos y cuartos (para F30).
_FIXTURE_FILES: dict[int, tuple[str, str]] = {
    2: ("R16", "r16_fixtures.csv"),
    3: ("QF", "r8_fixtures.csv"),
}
_FIXTURE_HEADER = ("draw_order", "date", "stage", "home_code", "away_code", "source")


def write_ko_fixtures(
    bracket: list[KoMatch],
    out_dir: Path | str = DEFAULT_KNOCKOUTS_DIR,
    *,
    source: str = "fotmob_official",
) -> dict[str, Path]:
    """Escribe ``r16_fixtures.csv`` (octavos) y ``r8_fixtures.csv`` (cuartos) (R6).

    Mismo esquema que ``r32_fixtures.csv``. Sólo se escriben partidos con AMBOS
    códigos FIFA resueltos (los ``TBD`` / ``Winner QF x`` se omiten, no se fuerza
    un código inválido). ``draw_order`` sigue el orden del bracket dentro de la etapa.

    Returns:
        Dict ``stage → ruta escrita`` para las etapas con al menos un partido resuelto.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    for ordinal, (stage_label, filename) in _FIXTURE_FILES.items():
        rows: list[tuple] = []
        draw = 0
        for km in bracket:
            if km.round_ordinal != ordinal:
                continue
            if not (km.home_code and km.away_code):
                continue  # equipo TBD → se omite (R6)
            draw += 1
            rows.append(
                (draw, km.date, stage_label, km.home_code, km.away_code, source)
            )
        path = out_dir / filename
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(_FIXTURE_HEADER)
            writer.writerows(rows)
        written[stage_label] = path
    return written


@dataclass
class KoIngestResult:
    """Resumen de una ingesta de eliminatorias (Feature 27)."""

    n_matches_bracket: int
    n_finished: int
    n_persisted: int
    fixtures_written: dict[str, Path]


def ingest_ko(
    fetched_at: str,
    league_id: int = 77,
    transport: KoTransport | None = None,
    bronze_dir: Path | str = FOTMOB_STATS_BRONZE_DIR,
    knockouts_dir: Path | str = DEFAULT_KNOCKOUTS_DIR,
    user_agent: str = DEFAULT_USER_AGENT,
    sleeper: Callable[[float], None] | None = None,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
) -> KoIngestResult:
    """Orquesta la ingesta de eliminatorias (Feature 27, R1/R3/R6).

    1. Descarga el bracket del playoff (``fetch_bracket``).
    2. Escribe ``r16_fixtures.csv`` / ``r8_fixtures.csv`` (``write_ko_fixtures``).
    3. Por cada partido KO **finished**, persiste marcador + stats en el bronze de
       fotmob_stats (``fetch_and_persist`` con override de goles desde el bracket).

    Con ``transport=None`` usa el transporte real (``requests``) — regla STOP.

    Args:
        fetched_at: ISO-8601 inyectado (sin reloj en lógica pura).
        league_id: ID de la liga fotmob (default 77 = Mundial 2026).
        transport: Callable url→html inyectable; None → transporte real.
        bronze_dir: Directorio del bronze de fotmob_stats.
        knockouts_dir: Directorio destino de los CSV de fixtures.
        user_agent: User-Agent para el transporte real.
        sleeper: Callable(seconds) para rate-limit antes de cada fetch de partido.
        rate_limit_seconds: Segundos entre requests reales.

    Returns:
        ``KoIngestResult`` con el resumen.
    """
    _transport = transport if transport is not None else _default_transport(user_agent)
    bracket = fetch_bracket(_transport, league_id=league_id)
    fixtures_written = write_ko_fixtures(bracket, knockouts_dir)

    finished = [km for km in bracket if km.finished and km.slug]
    n_persisted = 0
    for km in finished:
        raw: RawMatchStats = fetch_and_persist(
            _transport,
            ko_match_to_ref(km),
            fetched_at,
            out_dir=Path(bronze_dir),
            sleeper=sleeper,
            rate_limit_seconds=rate_limit_seconds,
            home_goals=km.home_goals,
            away_goals=km.away_goals,
        )
        n_persisted += 1 if (raw.home_goals is not None) else 0

    return KoIngestResult(
        n_matches_bracket=len(bracket),
        n_finished=len(finished),
        n_persisted=n_persisted,
        fixtures_written=fixtures_written,
    )
