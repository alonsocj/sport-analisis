"""tests/test_ingest_wiki.py — Tests de la ingesta Wikipedia (Feature 15, R1, R7).

Todos offline: transporte inyectable, fixtures JSON guardadas, sin red real,
sin reloj (fetched_at inyectado), sleeper=None (sin rate-limit en tests).

Mapeo trazabilidad (R1 → tests):
- test_mediawiki_transporte_inyectable_y_meta: R1 (transporte, bronze, meta, sha256)
- test_cache_24h_no_refetch: R1 (caché TTL 24h)
- test_articulo_sin_stats_no_aborta: R1 (degradación elegante)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingestion.wiki_stats import (
    DEFAULT_TTL_HOURS,
    WikiStatsResult,
    _build_api_url,
    _cache_is_valid,
    _parse_stats_from_html,
    ingest_wiki_article,
    ingest_wiki_stats,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers y transporte falso
# ---------------------------------------------------------------------------


def _fake_transport_from_fixture(fixture_name: str):
    """Crea un transporte falso que devuelve el contenido de un fixture JSON."""
    payload = (FIXTURES / fixture_name).read_text(encoding="utf-8")

    def _transport(url: str) -> str:  # noqa: ARG001
        return payload

    return _transport


def _wiki_api_response_with_html(html: str) -> str:
    """Envuelve HTML en la estructura de respuesta de la MediaWiki API."""
    doc = {
        "parse": {
            "title": "Test_Article",
            "pageid": 1234,
            "text": {"*": html},
        }
    }
    return json.dumps(doc)


def _make_stats_html(shots1: int, sot1: int, shots2: int, sot2: int) -> str:
    """Crea un HTML mínimo con tabla de estadísticas para dos equipos."""
    return (
        "<div>"
        "<table class='wikitable'>"
        "<tbody>"
        "<tr><th>Team</th><th>Shots</th><th>Shots on target</th><th>Possession (%)</th></tr>"
        f"<tr><td>MEX</td><td>{shots1}</td><td>{sot1}</td><td>55</td></tr>"
        f"<tr><td>USA</td><td>{shots2}</td><td>{sot2}</td><td>45</td></tr>"
        "</tbody>"
        "</table>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# R1: test_mediawiki_transporte_inyectable_y_meta
# ---------------------------------------------------------------------------


def test_mediawiki_transporte_inyectable_y_meta(tmp_path):
    """R1: el transporte inyectable obtiene el JSON de la API; persiste bronze + meta con sha256."""
    html = _make_stats_html(15, 5, 10, 3)
    transport = lambda url: _wiki_api_response_with_html(html)  # noqa: E731
    fetched_at = "2026-06-17T10:00:00+00:00"

    result = ingest_wiki_article(
        slug="2026_FIFA_World_Cup_Group_A",
        fetched_at=fetched_at,
        match_id="m001",
        home_code="MEX",
        away_code="USA",
        transport=transport,
        bronze_dir=tmp_path,
        ttl_hours=24,
        sleeper=None,  # sin rate-limit en tests (R7)
    )

    # Verifica el resultado
    assert isinstance(result, WikiStatsResult)
    assert result.slug == "2026_FIFA_World_Cup_Group_A"
    assert result.has_stats is True
    assert result.from_cache is False
    assert result.n_teams >= 1

    # Verifica que los archivos se crearon
    assert result.json_path.is_file()
    assert result.meta_path.is_file()

    # Verifica el contenido del bronze
    data = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert data["slug"] == "2026_FIFA_World_Cup_Group_A"
    assert data["has_stats"] is True
    assert len(data["stats"]) > 0

    # Verifica el sidecar de metadatos
    meta = json.loads(result.meta_path.read_text(encoding="utf-8"))
    assert "sha256" in meta
    assert len(meta["sha256"]) == 64  # SHA-256 hex digest
    assert meta["fetched_at"] == fetched_at
    assert "url" in meta


def test_mediawiki_transporte_inyectable_url_correcta(tmp_path):
    """R1: el transporte recibe la URL de la MediaWiki Action API, no otra."""
    captured_urls: list[str] = []

    def _transport(url: str) -> str:
        captured_urls.append(url)
        return _wiki_api_response_with_html(_make_stats_html(10, 4, 8, 2))

    ingest_wiki_article(
        slug="2026_FIFA_World_Cup_Group_B",
        fetched_at="2026-06-17T10:00:00+00:00",
        transport=_transport,
        bronze_dir=tmp_path,
        ttl_hours=24,
        sleeper=None,
    )

    assert len(captured_urls) == 1
    url = captured_urls[0]
    assert "en.wikipedia.org/w/api.php" in url
    assert "action=parse" in url
    assert "2026_FIFA_World_Cup_Group_B" in url
    assert "format=json" in url


# ---------------------------------------------------------------------------
# R1: test_cache_24h_no_refetch
# ---------------------------------------------------------------------------


def test_cache_24h_no_refetch(tmp_path):
    """R1: si el bronze existe y es fresco (dentro del TTL), no se re-descarga."""
    html = _make_stats_html(12, 4, 9, 3)
    call_count = [0]

    def _transport(url: str) -> str:  # noqa: ARG001
        call_count[0] += 1
        return _wiki_api_response_with_html(html)

    fetched_at = "2026-06-17T10:00:00+00:00"
    slug = "2026_FIFA_World_Cup_Group_C"

    # Primera llamada: descarga real
    result1 = ingest_wiki_article(
        slug=slug,
        fetched_at=fetched_at,
        transport=_transport,
        bronze_dir=tmp_path,
        ttl_hours=24,
        sleeper=None,
    )
    assert result1.from_cache is False
    assert call_count[0] == 1

    # Segunda llamada con el mismo fetched_at: desde caché, sin descarga
    result2 = ingest_wiki_article(
        slug=slug,
        fetched_at=fetched_at,
        transport=_transport,
        bronze_dir=tmp_path,
        ttl_hours=24,
        sleeper=None,
    )
    assert result2.from_cache is True
    assert call_count[0] == 1  # no se volvió a llamar al transporte


def test_cache_expirado_descarga_de_nuevo(tmp_path):
    """R1: si el bronze es más viejo que el TTL, se re-descarga."""
    html = _make_stats_html(8, 3, 6, 2)
    call_count = [0]

    def _transport(url: str) -> str:  # noqa: ARG001
        call_count[0] += 1
        return _wiki_api_response_with_html(html)

    slug = "2026_FIFA_World_Cup_Group_D"
    fetched_at_old = "2026-06-15T10:00:00+00:00"  # 2 días antes
    fetched_at_new = "2026-06-17T10:00:00+00:00"  # ahora

    # Primera llamada
    ingest_wiki_article(
        slug=slug,
        fetched_at=fetched_at_old,
        transport=_transport,
        bronze_dir=tmp_path,
        ttl_hours=24,
        sleeper=None,
    )
    assert call_count[0] == 1

    # Segunda llamada con timestamp más reciente (caché expirada)
    result2 = ingest_wiki_article(
        slug=slug,
        fetched_at=fetched_at_new,
        transport=_transport,
        bronze_dir=tmp_path,
        ttl_hours=24,
        sleeper=None,
    )
    assert result2.from_cache is False
    assert call_count[0] == 2  # se re-descargó


# ---------------------------------------------------------------------------
# R1: test_articulo_sin_stats_no_aborta
# ---------------------------------------------------------------------------


def test_articulo_sin_stats_no_aborta(tmp_path):
    """R1: artículo sin tabla de stats → se registra sin ellas, no aborta (degradación elegante)."""
    # HTML sin ninguna tabla de stats
    html = "<div><p>Este artículo no tiene estadísticas de tiros.</p></div>"
    transport = lambda url: _wiki_api_response_with_html(html)  # noqa: E731

    result = ingest_wiki_article(
        slug="2026_FIFA_World_Cup_Amistoso",
        fetched_at="2026-06-17T11:00:00+00:00",
        match_id="m002",
        home_code="ARG",
        away_code="BRA",
        transport=transport,
        bronze_dir=tmp_path,
        ttl_hours=24,
        sleeper=None,
    )

    # No aborta: devuelve resultado con has_stats=False
    assert isinstance(result, WikiStatsResult)
    assert result.has_stats is False
    assert result.n_teams == 0

    # El archivo bronze sí se crea (registro sin stats, no ausencia)
    assert result.json_path.is_file()
    data = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert data["has_stats"] is False
    assert data["stats"] == []


def test_respuesta_api_con_error_no_aborta(tmp_path):
    """R1: respuesta de API con error (artículo inexistente) → sin stats, no aborta."""
    api_error_response = json.dumps({
        "error": {"code": "missingtitle", "info": "The page you specified doesn't exist."},
        "servedby": "mw1234",
    })
    transport = lambda url: api_error_response  # noqa: E731

    result = ingest_wiki_article(
        slug="Articulo_Inexistente_2026",
        fetched_at="2026-06-17T12:00:00+00:00",
        transport=transport,
        bronze_dir=tmp_path,
        ttl_hours=24,
        sleeper=None,
    )
    assert result.has_stats is False
    assert result.json_path.is_file()


def test_ingest_wiki_stats_multiple(tmp_path):
    """R1: ingest_wiki_stats procesa múltiples artículos, degradando con gracia los sin stats."""
    html_ok = _make_stats_html(14, 6, 11, 4)
    html_no_stats = "<div><p>Sin estadísticas.</p></div>"

    call_idx = [0]
    responses = [
        _wiki_api_response_with_html(html_ok),
        _wiki_api_response_with_html(html_no_stats),
    ]

    def _transport(url: str) -> str:  # noqa: ARG001
        resp = responses[call_idx[0] % len(responses)]
        call_idx[0] += 1
        return resp

    matches = [
        {"slug": "Match_A", "match_id": "m1", "home_code": "MEX", "away_code": "POL"},
        {"slug": "Match_B", "match_id": "m2", "home_code": "ARG", "away_code": "AUS"},
    ]

    results = ingest_wiki_stats(
        matches=matches,
        fetched_at="2026-06-17T13:00:00+00:00",
        transport=_transport,
        bronze_dir=tmp_path,
        ttl_hours=24,
        sleeper=None,
    )

    assert len(results) == 2
    assert results[0].has_stats is True
    assert results[1].has_stats is False
    # Ninguno aborta
    for r in results:
        assert isinstance(r, WikiStatsResult)


def test_parse_stats_from_html_seguro():
    """R7: el parser usa lxml seguro (flavor='lxml'); nunca falla con HTML vacío."""
    # HTML vacío → [] sin excepción (degradación elegante)
    result = _parse_stats_from_html("")
    assert result == []

    # HTML sin tablas → []
    result2 = _parse_stats_from_html("<div><p>Sin tablas.</p></div>")
    assert result2 == []


def test_parse_stats_from_html_con_tabla_de_tiros():
    """R7: el parser extrae correctamente tiros y SoT de una tabla HTML."""
    html = _make_stats_html(15, 5, 10, 3)
    stats = _parse_stats_from_html(html)

    # Debe encontrar al menos una fila con shots y/o sot
    assert len(stats) > 0
    # Al menos una fila tiene shots o shots_on_target
    has_any = any(
        row.get("shots") is not None or row.get("shots_on_target") is not None
        for row in stats
    )
    assert has_any


def test_build_api_url_contiene_slug():
    """R1: la URL construida incluye el slug y los parámetros correctos de la API."""
    url = _build_api_url("2026_FIFA_World_Cup_Group_A")
    assert "en.wikipedia.org/w/api.php" in url
    assert "action=parse" in url
    assert "2026_FIFA_World_Cup_Group_A" in url
    assert "format=json" in url


# ---------------------------------------------------------------------------
# OBS-1: warning cuando hay tablas pero sin columnas de stats reconocidas
# ---------------------------------------------------------------------------


def test_parse_stats_tabla_sin_columnas_reconocidas_emite_warning():
    """OBS-1: tabla encontrada pero sin columnas de stats → UserWarning, resultado []."""
    # Tabla con columnas que no son reconocidas como stats de tiros
    html_tabla_irreconocible = (
        "<table>"
        "<thead><tr><th>País</th><th>Goles</th><th>Tarjetas</th></tr></thead>"
        "<tbody>"
        "<tr><td>MEX</td><td>2</td><td>1</td></tr>"
        "<tr><td>USA</td><td>1</td><td>2</td></tr>"
        "</tbody>"
        "</table>"
    )
    with pytest.warns(UserWarning, match="sin columnas de stats reconocidas"):
        result = _parse_stats_from_html(html_tabla_irreconocible)

    # El resultado sigue siendo [] (sin cobertura), igual que antes
    assert result == []
