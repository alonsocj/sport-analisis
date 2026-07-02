"""src/ingestion/roster.py — Ingesta de rosters R32 desde fotmob.com (Feature 21, R1–R2).

Obtiene los rosters de los 32 equipos de la fase eliminatoria del Mundial 2026
desde fotmob.com vía un transporte INYECTABLE (url → html), extrae el JSON
``__NEXT_DATA__`` embebido, persiste el resultado en bronze
``data/bronze/rosters/<slug>.json`` con un sidecar de metadatos (.meta.json),
aplica rate-limit inyectable, y degenera con elegancia cuando un partido no
tiene lineup publicado (registra el partido sin lineup en lugar de abortar, R1).

Seguridad / diseño:
- Transporte inyectable: cero red en tests (R1).
- ``fetched_at`` SIEMPRE inyectado; sin reloj en lógica pura (R1).
- Escritura solo bajo ``data/``.
- ``warnings.warn`` (no print) para issues no fatales (R1).
- Rate-limit: ``sleeper(rate_limit_seconds)`` ANTES del fetch (R1).
- UA identificable inyectable (R1).

Regla STOP de CLAUDE.md: ejecutar ``ingest_roster`` con transporte real
requiere aprobación previa del usuario.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .public_data import to_fifa_code

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

FOTMOB_BASE_URL = "https://www.fotmob.com"
FOTMOB_PLAYOFF_URL_TEMPLATE = (
    "https://www.fotmob.com/leagues/{league_id}/playoff/world-cup"
)

DEFAULT_BRONZE_DIR = Path("data") / "bronze" / "rosters"
DEFAULT_ROSTERS_CSV = Path("data") / "rosters" / "r32_rosters.csv"
DEFAULT_UNAVAILABLE_CSV = Path("data") / "rosters" / "r32_unavailable.csv"

DEFAULT_USER_AGENT = (
    "Mundial2026-ResearchBot/1.0 (academic; contact: aalonsocj14@gmail.com)"
)
DEFAULT_RATE_LIMIT_SECONDS: float = 2.0

# Alias de nombres fotmob → código FIFA (para nombres que to_fifa_code no cubre)
FOTMOB_ALIASES: dict[str, str] = {
    "Korea Republic": "KOR",
    "Côte d'Ivoire": "CIV",
    "Congo DR": "COD",
    "Democratic Republic of Congo": "COD",
    "Bosnia & Herzegovina": "BIH",
    "Curacao": "CUW",
    "USA": "USA",
    "US": "USA",
}

# ---------------------------------------------------------------------------
# Tipos inyectables
# ---------------------------------------------------------------------------

# Transporte inyectable: url → html (R1)
RosterTransport = Callable[[str], str]

# Sleeper inyectable: callable(float) para rate-limit (R1)
RosterSleeper = Callable[[float], None]


# ---------------------------------------------------------------------------
# Dataclasses de dominio
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchRef:
    """Referencia a un partido de la fase eliminatoria en fotmob (R1).

    Attributes:
        match_id: Identificador de partido fotmob (str).
        page_url: URL relativa del partido en fotmob (e.g. "/matches/...").
        home_team: Nombre del equipo local según fotmob.
        away_team: Nombre del equipo visitante según fotmob.
    """

    match_id: str
    page_url: str
    home_team: str
    away_team: str
    date: str = ""  # YYYY-MM-DD; propagado desde la league page (F23)


@dataclass
class TeamLineup:
    """Lineup de un equipo en un partido fotmob (R1).

    Attributes:
        name: Nombre del equipo según fotmob.
        starters: Lista de nombres de titulares.
        subs: Lista de nombres de suplentes.
        unavailable: Lista de dicts {name, reason} de jugadores no disponibles.
    """

    name: str
    starters: list[str]
    subs: list[str]
    unavailable: list[dict]


@dataclass
class RawLineup:
    """Resultado crudo de la descarga del lineup de un partido (R1).

    Attributes:
        match_ref: Referencia al partido.
        home: Lineup del equipo local (None si no disponible).
        away: Lineup del equipo visitante (None si no disponible).
        has_lineup: True si al menos un equipo tiene lineup.
    """

    match_ref: MatchRef
    home: TeamLineup | None = None
    away: TeamLineup | None = None
    has_lineup: bool = False


@dataclass
class RosterCoverage:
    """Resumen de cobertura de la ingesta de rosters (R1, R2).

    Attributes:
        n_matches: Total de partidos procesados.
        n_with_lineup: Partidos con al menos un lineup.
        n_teams_mapped: Equipos mapeados a código FIFA.
        n_teams_discarded: Equipos descartados por falta de mapeo FIFA.
    """

    n_matches: int
    n_with_lineup: int
    n_teams_mapped: int
    n_teams_discarded: int


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------


class RosterFetchError(RuntimeError):
    """Fallo al obtener una página de fotmob (R1)."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"Error fetching fotmob page '{url}': {reason}")
        self.url = url
        self.reason = reason


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------


def _fotmob_to_fifa_code(name: str) -> str | None:
    """Convierte un nombre de equipo fotmob a código FIFA (R1, R2).

    Orden de resolución:
    1. ``to_fifa_code(name)`` del módulo public_data (alias canónico del dataset).
    2. ``FOTMOB_ALIASES.get(name)`` (alias específicos de fotmob).
    3. None → equipo descartado con aviso.

    Args:
        name: Nombre del equipo tal como aparece en fotmob.

    Returns:
        Código FIFA de 3 letras o None si no hay mapeo.
    """
    code = to_fifa_code(name)
    if code is not None:
        return code
    return FOTMOB_ALIASES.get(name)


def _extract_next_data(html: str) -> dict:
    """Extrae el JSON de ``__NEXT_DATA__`` embebido en el HTML de fotmob (R1).

    Args:
        html: HTML de la página fotmob.

    Returns:
        Dict parseado del JSON de __NEXT_DATA__.

    Raises:
        ValueError: Si el script __NEXT_DATA__ no se encuentra en el HTML.
        json.JSONDecodeError: Si el contenido no es JSON válido.
    """
    pattern = re.compile(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        re.DOTALL,
    )
    match = pattern.search(html)
    if not match:
        raise ValueError("No se encontró __NEXT_DATA__ en el HTML.")
    return json.loads(match.group(1))


def _slug_from_ref(match_ref: MatchRef) -> str:
    """Genera un slug de sistema de archivos desde la referencia de partido (R1).

    Usa el último segmento de la page_url como slug base.

    Args:
        match_ref: Referencia al partido.

    Returns:
        Slug seguro para sistema de archivos.
    """
    return match_ref.page_url.rsplit("/", 1)[-1]


def _bronze_paths(slug: str, bronze_dir: Path) -> tuple[Path, Path]:
    """Rutas deterministas del bronze para un slug de partido (R1).

    Args:
        slug: Slug del partido.
        bronze_dir: Directorio raíz del bronze de rosters.

    Returns:
        Tuple (json_path, meta_path).
    """
    json_path = bronze_dir / f"{slug}.json"
    meta_path = bronze_dir / f"{slug}.meta.json"
    return json_path, meta_path


def _parse_team_lineup(team_data: dict) -> TeamLineup | None:
    """Parsea un dict de datos de equipo de fotmob a TeamLineup (R1).

    Args:
        team_data: Dict con keys name, starters, subs, unavailable de fotmob.

    Returns:
        TeamLineup o None si el nombre está vacío.
    """
    name = team_data.get("name", "")
    if not name:
        return None
    starters = [
        p.get("name", "")
        for p in team_data.get("starters", [])
        if p.get("name")
    ]
    subs = [
        p.get("name", "")
        for p in team_data.get("subs", [])
        if p.get("name")
    ]
    unavailable = [
        {
            "name": p.get("name", ""),
            "reason": p.get("unavailability", {}).get("reason", "Unknown"),
        }
        for p in team_data.get("unavailable", [])
        if p.get("name")
    ]
    return TeamLineup(name=name, starters=starters, subs=subs, unavailable=unavailable)


def _write_bronze(
    raw: RawLineup,
    url: str,
    fetched_at: str,
    json_path: Path,
    meta_path: Path,
) -> None:
    """Persiste el JSON de lineup y el sidecar de metadatos en bronze (R1).

    Args:
        raw: RawLineup con los datos del partido.
        url: URL de la página fotmob descargada.
        fetched_at: ISO-8601 timestamp inyectado (sin reloj).
        json_path: Ruta destino del JSON principal.
        meta_path: Ruta destino del sidecar de metadatos.
    """
    json_path.parent.mkdir(parents=True, exist_ok=True)

    def _team_to_dict(team: TeamLineup | None) -> dict | None:
        if team is None:
            return None
        return {
            "name": team.name,
            "starters": team.starters,
            "subs": team.subs,
            "unavailable": team.unavailable,
        }

    doc = {
        "match_id": raw.match_ref.match_id,
        "page_url": raw.match_ref.page_url,
        "home_team": raw.match_ref.home_team,
        "away_team": raw.match_ref.away_team,
        "has_lineup": raw.has_lineup,
        "home": _team_to_dict(raw.home),
        "away": _team_to_dict(raw.away),
    }
    raw_bytes = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    json_path.write_bytes(raw_bytes)

    meta = {
        "url": url,
        "fetched_at": fetched_at,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "match_id": raw.match_ref.match_id,
        "has_lineup": raw.has_lineup,
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _default_transport(
    user_agent: str = DEFAULT_USER_AGENT,
    sleeper: RosterSleeper | None = None,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
) -> RosterTransport:
    """Construye el transporte real con ``requests`` (import perezoso) (R1).

    El sleeper ya es gestionado externamente; este transporte NO aplica rate-limit
    internamente (el caller lo aplica antes de llamar al transporte).

    Args:
        user_agent: User-Agent HTTP header.
        sleeper: No usado aquí (rate-limit gestionado por el caller).
        rate_limit_seconds: No usado aquí.

    Returns:
        Transport callable que obtiene una URL y devuelve el HTML.
    """

    def _transport(url: str) -> str:
        import requests  # noqa: PLC0415 — import perezoso
        headers = {"User-Agent": user_agent}
        resp = requests.get(url, timeout=60, headers=headers)
        if not (200 <= resp.status_code < 300):
            raise RosterFetchError(url, f"HTTP {resp.status_code}")
        return resp.content.decode("utf-8", errors="replace")

    return _transport


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def fetch_playoff_match_urls(
    transport: RosterTransport,
    league_id: int = 77,
) -> list[MatchRef]:
    """Obtiene las URLs de los partidos R32 desde la página playoff de fotmob (R1).

    Parsea ``props.pageProps.playoff.rounds[stage=="1/16"].matchups``.
    Devuelve lista vacía (no lanza) si la estructura no se encuentra.

    Args:
        transport: Callable url→html inyectable (sin red en tests).
        league_id: ID de la liga fotmob (default 77 = Mundial 2026).

    Returns:
        Lista de MatchRef con los partidos del R32.
    """
    url = FOTMOB_PLAYOFF_URL_TEMPLATE.format(league_id=league_id)
    html = transport(url)
    try:
        data = _extract_next_data(html)
    except (ValueError, json.JSONDecodeError):
        return []

    playoff = (data.get("props") or {}).get("pageProps", {}).get("playoff", {})
    rounds = playoff.get("rounds", [])

    refs: list[MatchRef] = []
    for rnd in rounds:
        if str(rnd.get("stage", "")) != "1/16":
            continue
        for matchup in rnd.get("matchups", []):
            matches = matchup.get("matches", [])
            if not matches:
                continue
            m = matches[0]
            page_url = str(m.get("pageUrl", ""))
            match_id = str(m.get("matchId", ""))
            home_team = str(matchup.get("homeTeam", ""))
            away_team = str(matchup.get("awayTeam", ""))
            if page_url and match_id:
                refs.append(
                    MatchRef(
                        match_id=match_id,
                        page_url=page_url,
                        home_team=home_team,
                        away_team=away_team,
                    )
                )
    return refs


def fetch_match_lineup(
    transport: RosterTransport,
    match_ref: MatchRef,
    fetched_at: str,
    out_dir: Path = DEFAULT_BRONZE_DIR,
    *,
    sleeper: RosterSleeper | None = None,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
) -> RawLineup:
    """Descarga el lineup de un partido fotmob y persiste el bronze (R1).

    Si el transporte falla O el lineup no está disponible → devuelve RawLineup
    con has_lineup=False. No lanza excepción ni aborta. Persiste el bronze incluso
    para lineups vacíos.

    Args:
        transport: Callable url→html inyectable.
        match_ref: Referencia al partido.
        fetched_at: ISO-8601 timestamp inyectado (sin reloj en lógica pura).
        out_dir: Directorio raíz del bronze de rosters.
        sleeper: Callable(seconds) para rate-limit antes del fetch; None desactiva.
        rate_limit_seconds: Segundos entre requests reales.

    Returns:
        RawLineup con has_lineup=True si hay al menos un equipo con datos.
    """
    url = FOTMOB_BASE_URL + match_ref.page_url
    slug = _slug_from_ref(match_ref)
    json_path, meta_path = _bronze_paths(slug, Path(out_dir))

    # Rate-limit ANTES del fetch (R1)
    if sleeper is not None:
        sleeper(rate_limit_seconds)

    try:
        html = transport(url)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"Error de transporte para {url}: {exc}; saltando partido.",
            UserWarning,
            stacklevel=2,
        )
        return RawLineup(match_ref=match_ref, has_lineup=False)

    home_lineup: TeamLineup | None = None
    away_lineup: TeamLineup | None = None

    try:
        data = _extract_next_data(html)
        lineup_data = (
            (data.get("props") or {})
            .get("pageProps", {})
            .get("content", {})
            .get("lineup", {})
        )
        home_raw = lineup_data.get("homeTeam", {})
        away_raw = lineup_data.get("awayTeam", {})
        if home_raw:
            home_lineup = _parse_team_lineup(home_raw)
        if away_raw:
            away_lineup = _parse_team_lineup(away_raw)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"No se pudo parsear el lineup de {url}: {exc}",
            UserWarning,
            stacklevel=2,
        )

    has_lineup = home_lineup is not None or away_lineup is not None
    raw = RawLineup(
        match_ref=match_ref,
        home=home_lineup,
        away=away_lineup,
        has_lineup=has_lineup,
    )

    # Persistir bronze (R1)
    _write_bronze(raw, url, fetched_at, json_path, meta_path)
    return raw


def normalize_rosters(
    raw_lineups: list[RawLineup],
    rosters_csv: Path = DEFAULT_ROSTERS_CSV,
    unavailable_csv: Path = DEFAULT_UNAVAILABLE_CSV,
) -> tuple[list[dict], list[dict], RosterCoverage]:
    """Normaliza lineups a códigos FIFA y escribe los CSVs de salida (R2).

    Descarta equipos sin mapeo FIFA (warn, no aborta).
    Escribe:
    - rosters_csv con columnas ``team_code,scorer`` (disponibles: starters + subs).
    - unavailable_csv con columnas ``team_code,player,reason``.

    Args:
        raw_lineups: Lista de RawLineup de la ingesta.
        rosters_csv: Ruta destino del CSV de jugadores disponibles.
        unavailable_csv: Ruta destino del CSV de bajas.

    Returns:
        Tuple (available_rows, unavailable_rows, coverage).
    """
    available_rows: list[dict] = []
    unavailable_rows: list[dict] = []
    n_mapped = 0
    n_discarded = 0

    seen_teams: set[str] = set()

    for raw in raw_lineups:
        for team_lineup in (raw.home, raw.away):
            if team_lineup is None:
                continue
            code = _fotmob_to_fifa_code(team_lineup.name)
            if code is None:
                warnings.warn(
                    f"Equipo '{team_lineup.name}' sin mapeo FIFA; descartando.",
                    UserWarning,
                    stacklevel=2,
                )
                n_discarded += 1
                continue

            # Evitar duplicar el mismo equipo si aparece en varios partidos
            if code not in seen_teams:
                seen_teams.add(code)
                n_mapped += 1

            for player in team_lineup.starters + team_lineup.subs:
                available_rows.append({"team_code": code, "scorer": player})

            for entry in team_lineup.unavailable:
                unavailable_rows.append(
                    {
                        "team_code": code,
                        "player": entry.get("name", ""),
                        "reason": entry.get("reason", "Unknown"),
                    }
                )

    # Escribir rosters_csv (R2)
    rosters_csv = Path(rosters_csv)
    rosters_csv.parent.mkdir(parents=True, exist_ok=True)
    with rosters_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["team_code", "scorer"])
        writer.writeheader()
        writer.writerows(available_rows)

    # Escribir unavailable_csv (R2)
    unavailable_csv = Path(unavailable_csv)
    unavailable_csv.parent.mkdir(parents=True, exist_ok=True)
    with unavailable_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["team_code", "player", "reason"])
        writer.writeheader()
        writer.writerows(unavailable_rows)

    coverage = RosterCoverage(
        n_matches=len(raw_lineups),
        n_with_lineup=sum(1 for r in raw_lineups if r.has_lineup),
        n_teams_mapped=n_mapped,
        n_teams_discarded=n_discarded,
    )
    return available_rows, unavailable_rows, coverage


def ingest_roster(
    fetched_at: str,
    league_id: int = 77,
    transport: RosterTransport | None = None,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
    rosters_csv: Path = DEFAULT_ROSTERS_CSV,
    unavailable_csv: Path = DEFAULT_UNAVAILABLE_CSV,
    user_agent: str = DEFAULT_USER_AGENT,
    sleeper: RosterSleeper | None = None,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
) -> tuple[list[RawLineup], RosterCoverage]:
    """Orquesta la ingesta completa: URLs playoff → lineups → normalización (R1, R2).

    Flujo:
    1. Descarga la página playoff de fotmob y extrae las MatchRef del R32.
    2. Por cada partido, descarga el lineup con rate-limit inyectable.
    3. Normaliza los lineups a códigos FIFA y escribe los CSVs.

    Con ``transport=None`` usa el transporte real (requests).
    En tests se monkeypatchea esta función directamente o se inyecta un transporte.

    Args:
        fetched_at: ISO-8601 timestamp inyectado (sin reloj en lógica pura).
        league_id: ID de la liga fotmob (default 77 = Mundial 2026).
        transport: Callable url→html inyectable; None → transporte real.
        bronze_dir: Directorio raíz del bronze de rosters.
        rosters_csv: Ruta destino del CSV de disponibles.
        unavailable_csv: Ruta destino del CSV de bajas.
        user_agent: User-Agent para el transporte real.
        sleeper: Callable(seconds) para rate-limit; None desactiva.
        rate_limit_seconds: Segundos entre requests reales.

    Returns:
        Tuple (raw_lineups, coverage).
    """
    actual_transport = (
        transport
        if transport is not None
        else _default_transport(user_agent)
    )

    # R1: obtener referencias de partidos
    match_refs = fetch_playoff_match_urls(actual_transport, league_id=league_id)

    # R1: descargar lineup por partido
    raw_lineups: list[RawLineup] = []
    for ref in match_refs:
        raw = fetch_match_lineup(
            transport=actual_transport,
            match_ref=ref,
            fetched_at=fetched_at,
            out_dir=bronze_dir,
            sleeper=sleeper,
            rate_limit_seconds=rate_limit_seconds,
        )
        raw_lineups.append(raw)

    # R2: normalizar y escribir CSVs
    _, _, coverage = normalize_rosters(
        raw_lineups,
        rosters_csv=rosters_csv,
        unavailable_csv=unavailable_csv,
    )

    return raw_lineups, coverage
