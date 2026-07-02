"""src/ingestion/wiki_stats.py — Ingesta de stats de partido desde Wikipedia (Feature 15, R1).

Obtiene estadísticas de partido (tiros, tiros a puerta, posesión) vía la MediaWiki
Action API de Wikipedia, usando un transporte INYECTABLE (url → texto JSON), parsea
las tablas HTML embebidas con lxml de forma segura (parser seguro, dictamen
security-lead 2026-06-17), persiste el resultado en bronze
``data/bronze/wikipedia/<slug>.json`` con un sidecar de metadatos (.meta.json),
aplica caché TTL 24h, y degenera con elegancia cuando un artículo no trae stats
(registra el artículo sin stats en lugar de abortar, R1).

Seguridad (dictamen security-lead 2026-06-17):
- MediaWiki Action API (canal oficial, no scraping HTML directo).
- Parseo de HTML embebido con ``pandas.read_html(flavor='lxml')`` o con
  ``lxml.etree.HTMLParser(no_network=True, huge_tree=False)`` exclusivamente.
  NUNCA ``etree.fromstring`` ni ``etree.parse`` sobre HTML crudo.
- UA identificable inyectable; rate-limit ≥1 req/5s (sleeper inyectable,
  desactivado en tests para velocidad).
- ``fetched_at`` SIEMPRE inyectado; sin reloj en lógica pura.
- Escritura solo bajo ``data/``.

Regla STOP de CLAUDE.md: ejecutar ``ingest_wiki_stats`` con transporte real
requiere aprobación previa del usuario.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import warnings

import pandas as pd

# URL base de la MediaWiki Action API de Wikipedia (R1).
MEDIAWIKI_API_URL = "https://en.wikipedia.org/w/api.php"

# TTL por defecto en horas: si el bronze tiene menos de este tiempo, no re-fetch (R1).
DEFAULT_TTL_HOURS: int = 24

# User-Agent identificable por defecto (R1, dictamen security-lead).
DEFAULT_USER_AGENT = (
    "Mundial2026-ResearchBot/1.0 (academic; contact: aalonsocj14@gmail.com)"
)

# Directorio bronze de Wikipedia.
DEFAULT_BRONZE_DIR = Path("data") / "bronze"

# Transporte inyectable: url → texto JSON decodificado (R1).
WikiTransport = Callable[[str], str]

# Sleeper inyectable: callable(float) para rate-limit; desactivado en tests (R1).
WikiSleeper = Callable[[float], None]


@dataclass
class WikiStatsResult:
    """Resultado de la ingesta de un artículo de Wikipedia (R1).

    Attributes:
        slug: URL slug of the Wikipedia article.
        json_path: Path to the bronze JSON file.
        meta_path: Path to the bronze metadata sidecar.
        has_stats: True if statistics were found and parsed.
        from_cache: True if the bronze was loaded from cache (TTL valid).
        n_teams: Number of team stat rows found (0 if no stats).
    """

    slug: str
    json_path: Path
    meta_path: Path
    has_stats: bool
    from_cache: bool
    n_teams: int


class WikiFetchError(RuntimeError):
    """Fallo de la MediaWiki API: respuesta no exitosa o ausente (R1)."""

    def __init__(self, slug: str, reason: str) -> None:
        super().__init__(f"Error al obtener el artículo '{slug}': {reason}")
        self.slug = slug
        self.reason = reason


def _build_api_url(slug: str) -> str:
    """Construye la URL de la MediaWiki Action API para un artículo (R1).

    Args:
        slug: Wikipedia article slug (URL-encoded title).

    Returns:
        Full API URL string.
    """
    return (
        f"{MEDIAWIKI_API_URL}"
        f"?action=parse&page={slug}&prop=text&format=json&formatversion=2"
    )


def _default_transport(user_agent: str = DEFAULT_USER_AGENT) -> WikiTransport:
    """Construye el transporte real con ``requests`` (import perezoso) (R1).

    Args:
        user_agent: User-Agent header value.

    Returns:
        Transport callable that fetches a URL and returns the response text.
    """
    def _transport(url: str) -> str:
        import requests  # noqa: PLC0415 — import perezoso
        headers = {"User-Agent": user_agent}
        resp = requests.get(url, timeout=60, headers=headers)
        if not 200 <= resp.status_code < 300:
            raise WikiFetchError(url, f"HTTP {resp.status_code}")
        return resp.content.decode("utf-8", errors="replace")

    return _transport


def _default_sleeper(seconds: float) -> None:
    """Sleeper real con ``time.sleep`` (inyectable; desactivado en tests) (R1).

    Args:
        seconds: Number of seconds to sleep.
    """
    import time  # noqa: PLC0415
    time.sleep(seconds)


def _bronze_paths(slug: str, bronze_dir: Path) -> tuple[Path, Path]:
    """Rutas deterministas del bronze para un slug de artículo (R1).

    Args:
        slug: Wikipedia article slug.
        bronze_dir: Bronze directory root.

    Returns:
        Tuple of (json_path, meta_path).
    """
    base = Path(bronze_dir) / "wikipedia"
    safe_slug = slug.replace("/", "_").replace(" ", "_")
    json_path = base / f"{safe_slug}.json"
    meta_path = base / f"{safe_slug}.meta.json"
    return json_path, meta_path


def _cache_is_valid(json_path: Path, fetched_at: str, ttl_hours: int) -> bool:
    """Verifica si el bronze es fresco dentro del TTL (R1).

    Compara ``fetched_at`` con el ``fetched_at`` guardado en el sidecar meta.
    Si el sidecar no existe o el timestamp no es parseable → caché inválida.

    Args:
        json_path: Path to the bronze JSON file.
        fetched_at: Current timestamp (ISO-8601, INJECTED).
        ttl_hours: TTL in hours.

    Returns:
        True if valid cache exists within TTL.
    """
    meta_path = json_path.with_suffix("").parent / (json_path.stem + ".meta.json")
    if not json_path.is_file() or not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        cached_at_str = meta.get("fetched_at", "")
        # Parsear ambos timestamps y comparar diferencia
        from datetime import datetime, timezone as _tz  # noqa: PLC0415
        cached_at = datetime.fromisoformat(cached_at_str.replace("Z", "+00:00"))
        current_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        # Hacer ambos aware si alguno es naive
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=_tz.utc)
        if current_at.tzinfo is None:
            current_at = current_at.replace(tzinfo=_tz.utc)
        diff_hours = (current_at - cached_at).total_seconds() / 3600.0
        return 0 <= diff_hours < ttl_hours
    except Exception:  # noqa: BLE001
        return False


def _parse_stats_from_html(html: str) -> list[dict]:
    """Parsea tablas de estadísticas desde el HTML de la respuesta de la API (R1, security-lead).

    Usa ``pandas.read_html(flavor='lxml')`` para parsear las tablas de forma segura
    (flavor='lxml' usa lxml.html.HTMLParser internamente — safe-by-default, no XXE).
    NUNCA se pasa HTML crudo a ``etree.fromstring`` ni a ``etree.parse``.

    Busca tablas que contengan columnas de estadísticas de partido:
    tiros (shots), tiros a puerta (shots on target) y posesión (possession).

    Si no se encuentran tablas con stats → devuelve [] (sin cobertura, no aborta).

    Args:
        html: HTML string from the MediaWiki API response text field.

    Returns:
        List of dicts with keys: team_col_idx, shots, shots_on_target, possession.
        Empty list if no stats table found.
    """
    if not html or not html.strip():
        return []

    try:
        # flavor="lxml" → usa lxml.html.HTMLParser (safe, no XXE) — dictamen security-lead
        tables = pd.read_html(io.StringIO(html), flavor="lxml")
    except Exception:  # noqa: BLE001 — no aborta: artículo sin tablas es válido
        return []

    if not tables:
        return []

    stats_rows: list[dict] = []
    for df in tables:
        cols = [str(c).strip().lower() for c in df.columns]
        # Buscar columnas de tiros y posesión
        shots_col = _find_col(cols, ["shots", "tiros", "total shots"])
        sot_col = _find_col(cols, ["shots on target", "tiros a puerta", "on target", "sot"])
        poss_col = _find_col(cols, ["possession", "posesion", "posesión", "ball possession"])

        if shots_col is None and sot_col is None:
            # Esta tabla no tiene stats de tiros; buscar siguiente
            continue

        # Extraer filas con datos numéricos
        for _, row in df.iterrows():
            shots_val = _safe_numeric(row.iloc[cols.index(shots_col)] if shots_col else None)
            sot_val = _safe_numeric(row.iloc[cols.index(sot_col)] if sot_col else None)
            poss_val = _safe_numeric(row.iloc[cols.index(poss_col)] if poss_col else None)
            if shots_val is not None or sot_val is not None:
                # Hay datos de tiros en esta fila — es una fila de equipo
                stats_rows.append({
                    "shots": int(shots_val) if shots_val is not None else None,
                    "shots_on_target": int(sot_val) if sot_val is not None else None,
                    "possession": float(poss_val) if poss_val is not None else None,
                })

        if stats_rows:
            # Encontramos stats en esta tabla; no procesar más tablas
            break

    if tables and not stats_rows:
        warnings.warn(
            "Wikipedia: tabla(s) encontrada(s) pero sin columnas de stats reconocidas "
            "(posible cambio de estructura)",
            UserWarning,
            stacklevel=2,
        )

    return stats_rows


def _find_col(cols: list[str], keywords: list[str]) -> str | None:
    """Encuentra la primera columna cuyo nombre (lowercase) contiene alguna keyword.

    Args:
        cols: List of lowercased column names.
        keywords: Keywords to search for.

    Returns:
        Matching column name string, or None if not found.
    """
    for col in cols:
        for kw in keywords:
            if kw in col:
                return col
    return None


def _safe_numeric(value: object) -> float | None:
    """Convierte a float; None si no es numérico o si es NaN.

    Args:
        value: Value to convert.

    Returns:
        Float value or None.
    """
    if value is None:
        return None
    try:
        import math  # noqa: PLC0415
        f = float(value)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _write_bronze(
    slug: str,
    stats: list[dict],
    match_id: str | None,
    home_code: str | None,
    away_code: str | None,
    api_url: str,
    fetched_at: str,
    bronze_dir: Path,
) -> tuple[Path, Path]:
    """Persiste el JSON de stats y el sidecar de metadatos en bronze (R1).

    El JSON almacena las stats junto con los códigos de equipo para el emparejamiento.
    Si los códigos no se proporcionan, las stats se guardan sin mapeo (R2).

    Args:
        slug: Wikipedia article slug.
        stats: List of parsed stats dicts (may be empty if no coverage).
        match_id: Silver match_id for this article (optional).
        home_code: FIFA code of home team (optional).
        away_code: FIFA code of away team (optional).
        api_url: API URL used to fetch the article.
        fetched_at: ISO-8601 timestamp (INJECTED, no clock).
        bronze_dir: Bronze directory root.

    Returns:
        Tuple of (json_path, meta_path).
    """
    json_path, meta_path = _bronze_paths(slug, bronze_dir)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    # Construir la lista de stats con match_id y team_code para el emparejamiento (R2)
    enriched_stats: list[dict] = []
    if stats and match_id and home_code and away_code:
        # Asignar los equipos en orden: primera fila → home, segunda fila → away
        teams = [home_code, away_code]
        for i, stat_row in enumerate(stats[:2]):
            entry = dict(stat_row)
            entry["match_id"] = match_id
            entry["team_code"] = teams[i] if i < len(teams) else ""
            enriched_stats.append(entry)
    elif stats:
        # Sin match_id/codes, guardar las filas sin enriquecer
        enriched_stats = list(stats)

    doc = {
        "slug": slug,
        "match_id": match_id,
        "home_code": home_code,
        "away_code": away_code,
        "has_stats": len(enriched_stats) > 0,
        "stats": enriched_stats,
    }
    raw = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    json_path.write_bytes(raw)

    meta = {
        "url": api_url,
        "fetched_at": fetched_at,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "slug": slug,
        "has_stats": doc["has_stats"],
        "n_teams": len(enriched_stats),
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return json_path, meta_path


def ingest_wiki_article(
    slug: str,
    fetched_at: str,
    match_id: str | None = None,
    home_code: str | None = None,
    away_code: str | None = None,
    transport: WikiTransport | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    sleeper: WikiSleeper | None = None,
    rate_limit_seconds: float = 5.0,
) -> WikiStatsResult:
    """Obtiene, parsea y persiste en bronze las stats de un artículo de Wikipedia (R1).

    - Caché TTL: si el bronze existe y es fresco → no re-fetch (R1).
    - MediaWiki Action API con transporte inyectable (sin red en tests) (R1).
    - Rate-limit inyectable: ``sleeper(rate_limit_seconds)`` antes de la llamada
      real; desactivado en tests (sleeper=None) (R1).
    - Parseo seguro con lxml vía ``pandas.read_html(flavor='lxml')`` (R1, dictamen).
    - Si el artículo no trae stats → se persiste sin ellas (``has_stats=False``),
      sin abortar (R1).

    Args:
        slug: Wikipedia article slug (URL-encoded title, e.g.
            "2026_FIFA_World_Cup_Group_A").
        fetched_at: ISO-8601 timestamp (INJECTED; no clock in pure logic).
        match_id: Silver match_id to associate with this article.
        home_code: FIFA code of the home team.
        away_code: FIFA code of the away team.
        transport: Callable url→str; if None, uses the real HTTP transport.
        user_agent: User-Agent string for the real transport.
        bronze_dir: Bronze directory root.
        ttl_hours: Cache TTL in hours; fresh bronze skips re-fetch.
        sleeper: Callable(seconds) for rate-limiting; None disables sleep.
        rate_limit_seconds: Seconds to sleep between real requests.

    Returns:
        WikiStatsResult with paths and coverage information.
    """
    json_path, meta_path = _bronze_paths(slug, bronze_dir)

    # Caché TTL: si bronze fresco, no re-fetch (R1)
    if _cache_is_valid(json_path, fetched_at, ttl_hours):
        existing = json.loads(json_path.read_text(encoding="utf-8"))
        return WikiStatsResult(
            slug=slug,
            json_path=json_path,
            meta_path=meta_path,
            has_stats=existing.get("has_stats", False),
            from_cache=True,
            n_teams=len(existing.get("stats", [])),
        )

    # Rate-limit antes de la descarga real (inyectable; desactivado en tests) (R1)
    if sleeper is not None:
        sleeper(rate_limit_seconds)

    # Obtener el JSON de la MediaWiki API via transporte inyectable (R1)
    api_url = _build_api_url(slug)
    actual_transport = transport if transport is not None else _default_transport(user_agent)
    raw_text = actual_transport(api_url)

    # Parsear el JSON de respuesta de la API
    try:
        api_response = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise WikiFetchError(slug, f"respuesta JSON inválida: {exc}") from exc

    # Extraer el HTML embebido del campo parse.text (R1)
    html_content = ""
    parse_section = api_response.get("parse", {})
    text_field = parse_section.get("text")
    if isinstance(text_field, dict):
        # formatversion=1: {"*": "<html>"}
        html_content = text_field.get("*", "")
    elif isinstance(text_field, str):
        # formatversion=2: el HTML directamente
        html_content = text_field
    elif "error" in api_response:
        # El artículo no existe o hay error de API → sin stats, no aborta (R1)
        html_content = ""

    # Parseo seguro de tablas de stats (R1, security-lead)
    stats = _parse_stats_from_html(html_content)

    # Persistir bronze (R1)
    json_path, meta_path = _write_bronze(
        slug=slug,
        stats=stats,
        match_id=match_id,
        home_code=home_code,
        away_code=away_code,
        api_url=api_url,
        fetched_at=fetched_at,
        bronze_dir=bronze_dir,
    )

    return WikiStatsResult(
        slug=slug,
        json_path=json_path,
        meta_path=meta_path,
        has_stats=len(stats) > 0,
        from_cache=False,
        n_teams=min(len(stats), 2) if stats and match_id and home_code and away_code else 0,
    )


def ingest_wiki_stats(
    matches: list[dict],
    fetched_at: str,
    transport: WikiTransport | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    sleeper: WikiSleeper | None = None,
    rate_limit_seconds: float = 5.0,
) -> list[WikiStatsResult]:
    """Orquesta la ingesta de stats para múltiples partidos (R1).

    Cada entrada de ``matches`` debe ser un dict con al mínimo:
    - ``slug``: slug del artículo de Wikipedia.
    - ``match_id``: identificador del partido en el silver.
    - ``home_code``: código FIFA del equipo local.
    - ``away_code``: código FIFA del equipo visitante.

    Los artículos sin stats se registran sin ellas (degradación elegante, R1).

    Args:
        matches: List of match dicts with slug, match_id, home_code, away_code.
        fetched_at: ISO-8601 timestamp (INJECTED; no clock).
        transport: Injectable transport callable.
        user_agent: User-Agent for real transport.
        bronze_dir: Bronze directory root.
        ttl_hours: Cache TTL in hours.
        sleeper: Injectable sleeper for rate-limiting.
        rate_limit_seconds: Seconds between real requests.

    Returns:
        List of WikiStatsResult, one per match.
    """
    results: list[WikiStatsResult] = []
    for match in matches:
        slug = str(match.get("slug", ""))
        if not slug:
            continue
        result = ingest_wiki_article(
            slug=slug,
            fetched_at=fetched_at,
            match_id=str(match.get("match_id", "")) or None,
            home_code=str(match.get("home_code", "")) or None,
            away_code=str(match.get("away_code", "")) or None,
            transport=transport,
            user_agent=user_agent,
            bronze_dir=bronze_dir,
            ttl_hours=ttl_hours,
            sleeper=sleeper,
            rate_limit_seconds=rate_limit_seconds,
        )
        results.append(result)
    return results
