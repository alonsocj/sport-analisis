"""src/ingestion/fotmob_stats.py — Ingesta de stats por partido desde fotmob.com (Feature 23, R1–R2).

Obtiene las estadísticas por partido de los encuentros WC2026 jugados desde
fotmob.com vía un transporte INYECTABLE (url → html), extrae el JSON
``__NEXT_DATA__`` embebido, persiste el resultado en bronze
``data/bronze/fotmob_stats/<slug>.json`` con un sidecar de metadatos (.meta.json),
aplica rate-limit inyectable, y degrada con elegancia cuando un partido no
tiene stats publicadas (registra el partido sin stats en lugar de abortar, R1).

Seguridad / diseño:
- Transporte inyectable: cero red en tests (R1, R5).
- ``fetched_at`` SIEMPRE inyectado; sin reloj en lógica pura (R1).
- Escritura solo bajo ``data/``.
- ``warnings.warn`` (no print) para issues no fatales (R1, R5).
- Rate-limit: ``sleeper(rate_limit_seconds)`` ANTES del fetch (R1).
- UA identificable inyectable (R1).

Regla STOP de CLAUDE.md: ejecutar ``ingest_fotmob_stats`` con transporte real
requiere aprobación previa del usuario.
"""

from __future__ import annotations

import hashlib
import json
import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .public_data import to_fifa_code
from .roster import MatchRef  # reutilizamos el dataclass (match_id, page_url, home/away_team)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

FOTMOB_BASE_URL = "https://www.fotmob.com"

# Página de la liga (overview/matches) — partidos WC2026 con estado started/finished (R1)
FOTMOB_LEAGUE_URL_TEMPLATE = (
    "https://www.fotmob.com/leagues/{league_id}/overview/world-cup"
)

DEFAULT_BRONZE_DIR = Path("data") / "bronze" / "fotmob_stats"

DEFAULT_USER_AGENT = (
    "Mundial2026-ResearchBot/1.0 (academic; contact: aalonsocj14@gmail.com)"
)
DEFAULT_RATE_LIMIT_SECONDS: float = 2.0

# Alias fotmob → código FIFA (nombres que to_fifa_code del dataset no cubre) (R1, R2)
FOTMOB_STATS_ALIASES: dict[str, str] = {
    "Korea Republic": "KOR",
    "Côte d'Ivoire": "CIV",
    "Congo DR": "COD",
    "Democratic Republic of Congo": "COD",
    "Bosnia & Herzegovina": "BIH",
    "Curacao": "CUW",
    "USA": "USA",
    "US": "USA",
    "Ivory Coast": "CIV",
    "South Korea": "KOR",
    "DR Congo": "COD",
    "Czechia": "CZE",
    "Czech Republic": "CZE",
    "Turkiye": "TUR",
    "Türkiye": "TUR",
    "Turkey": "TUR",
}

# Mapeo título fotmob → clave del proyecto (R1)
_STAT_TITLE_MAP: dict[str, str] = {
    "Ball possession": "possession",
    "Expected goals (xG)": "xg",
    "Total shots": "shots",
    "Shots on target": "shots_on_target",
    "Corners": "corners",
}

# ---------------------------------------------------------------------------
# Tipos inyectables
# ---------------------------------------------------------------------------

# Transporte inyectable: url → html (R1, R5)
StatsTransport = Callable[[str], str]

# Sleeper inyectable: callable(float) para rate-limit (R1)
StatsSleeper = Callable[[float], None]


# ---------------------------------------------------------------------------
# Dataclasses de dominio
# ---------------------------------------------------------------------------


@dataclass
class RawMatchStats:
    """Resultado crudo de la descarga de stats de un partido (R1).

    Attributes:
        match_ref: Referencia al partido (reutiliza MatchRef de roster.py).
        has_stats: True si se pudieron extraer stats del partido.
        home_name: Nombre del equipo local según fotmob (para mapeo FIFA).
        away_name: Nombre del equipo visitante según fotmob.
        date: Fecha del partido en YYYY-MM-DD (vacía si no disponible).
        home: Dict de stats del equipo local (claves del proyecto).
        away: Dict de stats del equipo visitante (claves del proyecto).
    """

    match_ref: MatchRef
    has_stats: bool
    home_name: str = ""
    away_name: str = ""
    date: str = ""
    home: dict[str, float | None] = field(default_factory=dict)
    away: dict[str, float | None] = field(default_factory=dict)
    # F27-R2: marcador del partido (goles). None si el partido no ha terminado o
    # no se pudo extraer. Persistido en el JSON bronze para hacerlo auto-suficiente.
    home_goals: int | None = None
    away_goals: int | None = None


@dataclass
class StatsCoverage:
    """Resumen de cobertura de la ingesta de stats (R1, R2).

    Attributes:
        n_matches: Total de partidos procesados.
        n_with_stats: Partidos con stats extraídas.
        n_teams_mapped: Equipos mapeados a código FIFA.
        n_teams_discarded: Equipos descartados por falta de mapeo FIFA.
    """

    n_matches: int
    n_with_stats: int
    n_teams_mapped: int
    n_teams_discarded: int


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------


class StatsFetchError(RuntimeError):
    """Fallo al obtener una página de fotmob (R1)."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"Error fetching fotmob page '{url}': {reason}")
        self.url = url
        self.reason = reason


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------


def _fotmob_stats_to_fifa_code(name: str) -> str | None:
    """Convierte un nombre de equipo fotmob a código FIFA (R1, R2).

    Orden de resolución:
    1. ``to_fifa_code(name)`` del módulo public_data (alias canónico del dataset).
    2. ``FOTMOB_STATS_ALIASES.get(name)`` (alias específicos de fotmob para stats).
    3. None → equipo descartado con aviso.

    Args:
        name: Nombre del equipo tal como aparece en fotmob.

    Returns:
        Código FIFA de 3 letras o None si no hay mapeo.
    """
    code = to_fifa_code(name)
    if code is not None:
        return code
    return FOTMOB_STATS_ALIASES.get(name)


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

    Usa el último segmento de page_url (sin fragment ``#...``) como slug.

    Args:
        match_ref: Referencia al partido.

    Returns:
        Slug seguro para sistema de archivos.
    """
    url = match_ref.page_url.split("#")[0]
    return url.rsplit("/", 1)[-1]


def _bronze_paths(slug: str, bronze_dir: Path) -> tuple[Path, Path]:
    """Rutas deterministas del bronze para un slug de partido (R1).

    Args:
        slug: Slug del partido.
        bronze_dir: Directorio raíz del bronze de fotmob_stats.

    Returns:
        Tuple (json_path, meta_path).
    """
    json_path = bronze_dir / f"{slug}.json"
    meta_path = bronze_dir / f"{slug}.meta.json"
    return json_path, meta_path


def _parse_stat_value(raw: Any) -> float | None:
    """Convierte un valor crudo de stat fotmob a float nullable (R1).

    Args:
        raw: Valor crudo (int, float, str, None) del campo stats de fotmob.

    Returns:
        float o None si el valor es None.
    """
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _utc_to_date(utc_time: str) -> str:
    """Convierte un ISO-8601 de fotmob (incluido 'Z') a YYYY-MM-DD (R1).

    Args:
        utc_time: Cadena ISO-8601 de fotmob (e.g. "2026-06-15T15:00:00.000Z").

    Returns:
        Fecha en formato YYYY-MM-DD o cadena vacía si no parseable.
    """
    if not utc_time:
        return ""
    try:
        dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _extract_team_stats(stats_groups: list[dict]) -> tuple[dict, dict]:
    """Extrae las stats de local y visitante desde los grupos de stats fotmob (R1).

    Recorre todos los grupos y sus sub-stats buscando títulos del mapeo
    ``_STAT_TITLE_MAP``. Para ``Yellow cards`` y ``Red cards`` acumula la suma
    para producir ``cards`` (null → 0 en la suma, según diseño R1).

    Args:
        stats_groups: Lista de grupos ``{title, stats:[{title, stats:[home,away]}]}``.

    Returns:
        Tuple (home_dict, away_dict) con claves del proyecto (possession, xg, shots,
        shots_on_target, corners, cards).
    """
    home: dict[str, float | None] = {}
    away: dict[str, float | None] = {}
    yellow_home: float = 0.0
    yellow_away: float = 0.0
    red_home: float = 0.0
    red_away: float = 0.0
    has_cards = False

    for group in stats_groups:
        sub_stats = group.get("stats") or []
        for stat in sub_stats:
            title = stat.get("title", "")
            values = stat.get("stats") or []
            if len(values) < 2:
                continue

            val_home = values[0]
            val_away = values[1]

            if title in _STAT_TITLE_MAP:
                key = _STAT_TITLE_MAP[title]
                home[key] = _parse_stat_value(val_home)
                away[key] = _parse_stat_value(val_away)
            elif title == "Yellow cards":
                yellow_home = float(val_home) if val_home is not None else 0.0
                yellow_away = float(val_away) if val_away is not None else 0.0
                has_cards = True
            elif title == "Red cards":
                red_home = float(val_home) if val_home is not None else 0.0
                red_away = float(val_away) if val_away is not None else 0.0
                has_cards = True

    if has_cards:
        home["cards"] = yellow_home + red_home
        away["cards"] = yellow_away + red_away

    return home, away


def _write_bronze(
    raw: RawMatchStats,
    url: str,
    fetched_at: str,
    json_path: Path,
    meta_path: Path,
) -> None:
    """Persiste el JSON de stats y el sidecar de metadatos en bronze (R1).

    Args:
        raw: RawMatchStats con los datos del partido.
        url: URL de la página fotmob descargada.
        fetched_at: ISO-8601 timestamp inyectado (sin reloj).
        json_path: Ruta destino del JSON principal.
        meta_path: Ruta destino del sidecar de metadatos.
    """
    json_path.parent.mkdir(parents=True, exist_ok=True)

    doc = {
        "match_id": raw.match_ref.match_id,
        "page_url": raw.match_ref.page_url,
        "home_name": raw.home_name,
        "away_name": raw.away_name,
        "date": raw.date,
        "has_stats": raw.has_stats,
        # F27-R2: marcador (goles) para que el JSON sea auto-suficiente. None si no aplica.
        "home_goals": raw.home_goals,
        "away_goals": raw.away_goals,
        "home": raw.home,
        "away": raw.away,
    }
    raw_bytes = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    json_path.write_bytes(raw_bytes)

    meta = {
        "url": url,
        "fetched_at": fetched_at,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "match_id": raw.match_ref.match_id,
        "has_stats": raw.has_stats,
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _default_transport(
    user_agent: str = DEFAULT_USER_AGENT,
) -> StatsTransport:
    """Construye el transporte real con ``requests`` (import perezoso) (R1).

    El rate-limit NO se aplica aquí; el caller lo gestiona mediante sleeper.

    Args:
        user_agent: User-Agent HTTP header.

    Returns:
        Transport callable que obtiene una URL y devuelve el HTML.
    """

    def _transport(url: str) -> str:
        import requests  # noqa: PLC0415 — import perezoso

        headers = {"User-Agent": user_agent}
        resp = requests.get(url, timeout=60, headers=headers)
        if not (200 <= resp.status_code < 300):
            raise StatsFetchError(url, f"HTTP {resp.status_code}")
        return resp.content.decode("utf-8", errors="replace")

    return _transport


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def fetch_match_urls(
    transport: StatsTransport,
    league_id: int = 77,
) -> list[MatchRef]:
    """Obtiene las URLs de los partidos WC2026 jugados desde la overview page de la liga (R1).

    Parsea ``props.pageProps.fixtures.allMatches`` buscando partidos con
    ``status.finished`` verdadero. ``home`` y ``away`` son strings directos en el
    JSON de fotmob (no objetos). Devuelve lista vacía (no lanza) si la estructura
    no se encuentra.

    Args:
        transport: Callable url→html inyectable (sin red en tests).
        league_id: ID de la liga fotmob (default 77 = Mundial 2026).

    Returns:
        Lista de MatchRef con los partidos finalizados.
    """
    url = FOTMOB_LEAGUE_URL_TEMPLATE.format(league_id=league_id)
    html = transport(url)
    try:
        data = _extract_next_data(html)
    except (ValueError, json.JSONDecodeError):
        return []

    page_props = (data.get("props") or {}).get("pageProps", {})
    # La overview page de fotmob expone los fixtures en pageProps.fixtures.allMatches
    fixtures_data = page_props.get("fixtures") or {}
    all_matches = fixtures_data.get("allMatches") or []

    refs: list[MatchRef] = []
    for m in all_matches:
        status = m.get("status") or {}
        if not status.get("finished"):
            continue
        page_url = str(m.get("pageUrl") or "")
        match_id = str(m.get("id") or "")
        # home/away son strings directos en fotmob (no objetos)
        home_name = str(m.get("home") or "")
        away_name = str(m.get("away") or "")
        # Fecha desde status.utcTime (YYYY-MM-DD); garantiza bronze con date no vacío (F23 BUG1)
        utc_time = str(status.get("utcTime") or "")
        match_date = utc_time[:10] if len(utc_time) >= 10 else ""
        if page_url and match_id:
            refs.append(
                MatchRef(
                    match_id=match_id,
                    page_url=page_url,
                    home_team=home_name,
                    away_team=away_name,
                    date=match_date,
                )
            )
    return refs


def parse_match_score(html: str) -> tuple[int | None, int | None]:
    """Extrae el marcador (home_goals, away_goals) del __NEXT_DATA__ del partido (F27-R2).

    Lee ``props.pageProps.header.teams[*].score`` (0=home, 1=away). Es independiente
    de las stats: un partido finished siempre tiene marcador aunque no publique stats.
    Devuelve ``(None, None)`` si la estructura no está o los valores no son enteros.

    Args:
        html: HTML de la página de partido de fotmob.

    Returns:
        Tuple ``(home_goals, away_goals)`` con enteros o ``None``.
    """
    try:
        data = _extract_next_data(html)
    except (ValueError, json.JSONDecodeError):
        return (None, None)
    page_props = (data.get("props") or {}).get("pageProps", {})
    header = page_props.get("header") or {}
    teams = header.get("teams") or []
    if len(teams) < 2:
        return (None, None)

    def _score(team: Any) -> int | None:
        if not isinstance(team, dict):
            return None
        val = team.get("score")
        if isinstance(val, bool):  # bool es subclase de int; excluir explícitamente
            return None
        if isinstance(val, int):
            return val
        return None

    return (_score(teams[0]), _score(teams[1]))


def parse_match_stats(html: str) -> dict[str, Any]:
    """Parsea las stats de un partido desde el HTML de fotmob (R1).

    Extrae ``content.stats.Periods.All.stats`` y mapea los títulos fotmob a
    claves del proyecto. Los valores de ``Yellow cards`` y ``Red cards`` se
    suman para producir ``cards`` (null → 0 en la suma, diseño R1).

    Args:
        html: HTML de la página de partido de fotmob.

    Returns:
        Dict con keys:
        - ``home``: dict de stats del equipo local (possession, xg, shots, etc.)
        - ``away``: dict de stats del equipo visitante
        - ``teams``: tuple (home_name, away_name) desde ``general``
        - ``date``: str YYYY-MM-DD desde ``general.matchTimeUTC``

    Raises:
        ValueError: Si no se puede extraer __NEXT_DATA__ o no hay stats.
    """
    data = _extract_next_data(html)
    page_props = (data.get("props") or {}).get("pageProps", {})

    # Nombres de equipo y fecha desde ``general``
    general = page_props.get("general") or {}
    home_name = (general.get("homeTeam") or {}).get("name", "")
    away_name = (general.get("awayTeam") or {}).get("name", "")
    match_time = general.get("matchTimeUTC") or general.get("matchTime") or ""
    date = _utc_to_date(match_time)

    # Stats
    content = page_props.get("content") or {}
    stats_root = content.get("stats") or {}
    periods = stats_root.get("Periods") or {}
    all_period = periods.get("All") or {}
    stats_groups: list[dict] = all_period.get("stats") or []

    if not stats_groups:
        raise ValueError("No hay stats disponibles en Periods.All para este partido.")

    home_stats, away_stats = _extract_team_stats(stats_groups)

    return {
        "home": home_stats,
        "away": away_stats,
        "teams": (home_name, away_name),
        "date": date,
    }


def fetch_and_persist(
    transport: StatsTransport,
    match_ref: MatchRef,
    fetched_at: str,
    out_dir: Path = DEFAULT_BRONZE_DIR,
    *,
    sleeper: StatsSleeper | None = None,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
    home_goals: int | None = None,
    away_goals: int | None = None,
) -> RawMatchStats:
    """Descarga las stats de un partido fotmob y persiste el bronze (R1).

    Si el transporte falla O el partido no tiene stats → devuelve RawMatchStats
    con has_stats=False. No lanza excepción ni aborta. Persiste el bronze
    incluso para partidos sin stats (registro vacío).

    Args:
        transport: Callable url→html inyectable.
        match_ref: Referencia al partido.
        fetched_at: ISO-8601 timestamp inyectado (sin reloj en lógica pura).
        out_dir: Directorio raíz del bronze de fotmob_stats.
        sleeper: Callable(seconds) para rate-limit antes del fetch; None desactiva.
        rate_limit_seconds: Segundos entre requests reales.

    Returns:
        RawMatchStats con has_stats=True si se extrajeron stats correctamente.
    """
    page_url_clean = match_ref.page_url.split("#")[0]
    url = FOTMOB_BASE_URL + page_url_clean
    slug = _slug_from_ref(match_ref)
    json_path, meta_path = _bronze_paths(slug, Path(out_dir))

    # Rate-limit ANTES del fetch (R1)
    if sleeper is not None:
        sleeper(rate_limit_seconds)

    # Intento de descarga
    try:
        html = transport(url)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"Error de transporte para {url}: {exc}; saltando partido.",
            UserWarning,
            stacklevel=2,
        )
        return RawMatchStats(
            match_ref=match_ref,
            has_stats=False,
            home_name=match_ref.home_team,
            away_name=match_ref.away_team,
            home_goals=home_goals,
            away_goals=away_goals,
        )

    # Intento de parseo
    home_stats: dict[str, float | None] = {}
    away_stats: dict[str, float | None] = {}
    home_name = match_ref.home_team
    away_name = match_ref.away_team
    date = ""
    has_stats = False

    try:
        parsed = parse_match_stats(html)
        home_stats = parsed["home"]
        away_stats = parsed["away"]
        home_name_parsed, away_name_parsed = parsed["teams"]
        if home_name_parsed:
            home_name = home_name_parsed
        if away_name_parsed:
            away_name = away_name_parsed
        date = parsed["date"]
        has_stats = bool(home_stats or away_stats)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"No se pudieron extraer stats de {url}: {exc}; partido sin stats.",
            UserWarning,
            stacklevel=2,
        )

    # BUG1: si parse_match_stats no extrajo la fecha (fallo o estructura diferente),
    # usar la fecha propagada desde la league page (siempre presente en MatchRef.date)
    if not date:
        date = match_ref.date

    # F27-R2: marcador. Prioridad al override explícito (p.ej. del bracket playoff);
    # si no, se parsea de la página (independiente de las stats: un finished sin stats
    # igual tiene marcador).
    hg, ag = home_goals, away_goals
    if hg is None and ag is None:
        hg, ag = parse_match_score(html)

    raw = RawMatchStats(
        match_ref=match_ref,
        has_stats=has_stats,
        home_name=home_name,
        away_name=away_name,
        date=date,
        home=home_stats,
        away=away_stats,
        home_goals=hg,
        away_goals=ag,
    )

    # Persistir bronze (R1)
    _write_bronze(raw, url, fetched_at, json_path, meta_path)
    return raw


def normalize_stats(
    raw_list: list[RawMatchStats],
) -> tuple[list[dict], StatsCoverage]:
    """Normaliza stats a códigos FIFA y produce filas por date+equipos (R2).

    Descarta partidos sin stats (has_stats=False). Descarta equipos sin mapeo
    FIFA con ``warnings.warn``, no aborta.

    Args:
        raw_list: Lista de RawMatchStats de la ingesta.

    Returns:
        Tuple (rows, coverage) donde rows tiene claves
        (date, home_code, away_code, home_*, away_*) con las stats del proyecto.
    """
    rows: list[dict] = []
    n_mapped = 0
    n_discarded = 0

    for raw in raw_list:
        if not raw.has_stats:
            continue
        home_code = _fotmob_stats_to_fifa_code(raw.home_name)
        away_code = _fotmob_stats_to_fifa_code(raw.away_name)

        if home_code is None:
            warnings.warn(
                f"Equipo local '{raw.home_name}' sin mapeo FIFA; omitiendo partido.",
                UserWarning,
                stacklevel=2,
            )
            n_discarded += 1
            continue
        if away_code is None:
            warnings.warn(
                f"Equipo visitante '{raw.away_name}' sin mapeo FIFA; omitiendo partido.",
                UserWarning,
                stacklevel=2,
            )
            n_discarded += 1
            continue

        n_mapped += 2
        row: dict = {
            "date": raw.date,
            "home_code": home_code,
            "away_code": away_code,
        }
        for stat_key in ("possession", "xg", "shots", "shots_on_target", "corners", "cards"):
            row[f"home_{stat_key}"] = raw.home.get(stat_key)
            row[f"away_{stat_key}"] = raw.away.get(stat_key)
        rows.append(row)

    coverage = StatsCoverage(
        n_matches=len(raw_list),
        n_with_stats=sum(1 for r in raw_list if r.has_stats),
        n_teams_mapped=n_mapped,
        n_teams_discarded=n_discarded,
    )
    return rows, coverage


def ingest_fotmob_stats(
    fetched_at: str,
    league_id: int = 77,
    transport: StatsTransport | None = None,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
    user_agent: str = DEFAULT_USER_AGENT,
    sleeper: StatsSleeper | None = None,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
) -> tuple[list[RawMatchStats], StatsCoverage]:
    """Orquesta la ingesta completa: URLs de partidos → stats → normalización (R1, R2).

    Flujo:
    1. Descarga la página de la liga de fotmob y extrae las MatchRef de partidos jugados.
    2. Por cada partido, descarga las stats con rate-limit inyectable.
    3. Normaliza las stats a códigos FIFA y calcula la cobertura.

    Con ``transport=None`` usa el transporte real (requests).
    En tests se inyecta un transporte de fixture.

    Args:
        fetched_at: ISO-8601 timestamp inyectado (sin reloj en lógica pura).
        league_id: ID de la liga fotmob (default 77 = Mundial 2026).
        transport: Callable url→html inyectable; None → transporte real.
        bronze_dir: Directorio raíz del bronze de fotmob_stats.
        user_agent: User-Agent para el transporte real.
        sleeper: Callable(seconds) para rate-limit; None desactiva.
        rate_limit_seconds: Segundos entre requests reales.

    Returns:
        Tuple (raw_list, coverage).
    """
    actual_transport = (
        transport if transport is not None else _default_transport(user_agent)
    )

    # R1: obtener referencias de partidos jugados/iniciados
    match_refs = fetch_match_urls(actual_transport, league_id=league_id)

    # R1: descargar stats por partido (con rate-limit)
    raw_list: list[RawMatchStats] = []
    for ref in match_refs:
        raw = fetch_and_persist(
            transport=actual_transport,
            match_ref=ref,
            fetched_at=fetched_at,
            out_dir=bronze_dir,
            sleeper=sleeper,
            rate_limit_seconds=rate_limit_seconds,
        )
        raw_list.append(raw)

    # R2: normalizar a filas FIFA y calcular cobertura
    _, coverage = normalize_stats(raw_list)

    return raw_list, coverage
