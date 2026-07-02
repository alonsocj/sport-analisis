"""tests/test_ingest_roster.py — Tests de ingesta de rosters fotmob (Feature 21, R1, R4, R5).

Todos offline: transporte inyectable, JSON sintético embebido en el test, sin red
real, sin reloj (fetched_at inyectado), sleeper=None (sin rate-limit en tests).

Mapeo de trazabilidad:
- test_transporte_inyectable_y_bronze_meta    → R1 (transporte, bronze, meta, sha256)
- test_partido_sin_lineup_no_aborta           → R1, R5 (degradación elegante)
- test_error_red_salta_partido                → R1, R5 (error de transporte no fatal)
- test_cli_ingest_roster                      → R4 (subcomando CLI)
- test_subcomandos_exactos_intactos           → R4 (15 subcomandos exactos)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.ingestion.roster import (
    MatchRef,
    RawLineup,
    RosterCoverage,
    TeamLineup,
    _bronze_paths,
    _extract_next_data,
    _slug_from_ref,
    fetch_match_lineup,
    fetch_playoff_match_urls,
)

# ---------------------------------------------------------------------------
# Constantes y helpers de test
# ---------------------------------------------------------------------------

FETCHED_AT = "2026-06-27T10:00:00+00:00"

# JSON mínimo de una página MATCH fotmob con lineup
_MATCH_NEXT_DATA = {
    "props": {
        "pageProps": {
            "content": {
                "lineup": {
                    "homeTeam": {
                        "name": "South Africa",
                        "starters": [
                            {"name": "Ronwen Williams"},
                            {"name": "Siyanda Xulu"},
                        ],
                        "subs": [{"name": "Ricardo Goss"}],
                        "unavailable": [
                            {
                                "name": "Percy Tau",
                                "unavailability": {"reason": "Injured"},
                            }
                        ],
                    },
                    "awayTeam": {
                        "name": "Canada",
                        "starters": [
                            {"name": "Maxime Crepeau"},
                            {"name": "Alphonso Davies"},
                        ],
                        "subs": [{"name": "Jonathan David"}],
                        "unavailable": [],
                    },
                }
            }
        }
    }
}

# JSON mínimo de la página PLAYOFF fotmob con una llave R32
_PLAYOFF_NEXT_DATA = {
    "props": {
        "pageProps": {
            "playoff": {
                "rounds": [
                    {
                        "stage": "1/16",
                        "matchups": [
                            {
                                "homeTeam": "South Africa",
                                "awayTeam": "Canada",
                                "matches": [
                                    {
                                        "matchId": 4519287,
                                        "pageUrl": "/matches/south-africa-vs-canada/17s1wd",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }
    }
}


def _make_html(next_data: dict) -> str:
    """Envuelve next_data en el HTML mínimo de fotmob."""
    payload = json.dumps(next_data)
    return (
        f'<html><head>'
        f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>'
        f'</head><body></body></html>'
    )


def _make_match_ref() -> MatchRef:
    return MatchRef(
        match_id="4519287",
        page_url="/matches/south-africa-vs-canada/17s1wd",
        home_team="South Africa",
        away_team="Canada",
    )


# ---------------------------------------------------------------------------
# R1: test_transporte_inyectable_y_bronze_meta
# ---------------------------------------------------------------------------


def test_transporte_inyectable_y_bronze_meta(tmp_path):
    """R1: el transporte inyectable descarga el HTML; se persiste bronze + meta con sha256."""
    match_ref = _make_match_ref()
    html = _make_html(_MATCH_NEXT_DATA)

    transport = lambda url: html  # noqa: E731

    raw = fetch_match_lineup(
        transport=transport,
        match_ref=match_ref,
        fetched_at=FETCHED_AT,
        out_dir=tmp_path,
        sleeper=None,  # sin rate-limit en tests
    )

    # Resultado básico
    assert isinstance(raw, RawLineup)
    assert raw.has_lineup is True
    assert raw.home is not None
    assert raw.away is not None
    assert raw.home.name == "South Africa"
    assert "Ronwen Williams" in raw.home.starters
    assert "Ricardo Goss" in raw.home.subs
    assert any(u["name"] == "Percy Tau" for u in raw.home.unavailable)

    # Bronze persiste
    slug = _slug_from_ref(match_ref)
    json_path, meta_path = _bronze_paths(slug, tmp_path)
    assert json_path.is_file(), "Falta el JSON de bronze"
    assert meta_path.is_file(), "Falta el sidecar .meta.json"

    doc = json.loads(json_path.read_text(encoding="utf-8"))
    assert doc["match_id"] == "4519287"
    assert doc["has_lineup"] is True
    assert doc["home"]["name"] == "South Africa"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["fetched_at"] == FETCHED_AT
    assert "sha256" in meta
    assert len(meta["sha256"]) == 64  # sha256 hexdigest = 64 chars
    assert meta["has_lineup"] is True


def test_fetch_playoff_match_urls(tmp_path):
    """R1: fetch_playoff_match_urls extrae las MatchRef del JSON playoff."""
    html = _make_html(_PLAYOFF_NEXT_DATA)
    transport = lambda url: html  # noqa: E731

    refs = fetch_playoff_match_urls(transport=transport, league_id=77)

    assert len(refs) == 1
    ref = refs[0]
    assert ref.match_id == "4519287"
    assert ref.page_url == "/matches/south-africa-vs-canada/17s1wd"
    assert ref.home_team == "South Africa"
    assert ref.away_team == "Canada"


def test_fetch_playoff_estructura_ausente_devuelve_lista_vacia():
    """R1: si la estructura playoff no existe → devuelve [] sin lanzar."""
    html = _make_html({"props": {"pageProps": {}}})
    transport = lambda url: html  # noqa: E731

    refs = fetch_playoff_match_urls(transport=transport)
    assert refs == []


# ---------------------------------------------------------------------------
# R1, R5: test_partido_sin_lineup_no_aborta
# ---------------------------------------------------------------------------


def test_partido_sin_lineup_no_aborta(tmp_path):
    """R1 (R5): un partido sin lineup en __NEXT_DATA__ no aborta; has_lineup=False."""
    match_ref = _make_match_ref()
    # HTML sin lineup (solo estructura vacía)
    empty_data = {"props": {"pageProps": {"content": {"lineup": {}}}}}
    html = _make_html(empty_data)
    transport = lambda url: html  # noqa: E731

    raw = fetch_match_lineup(
        transport=transport,
        match_ref=match_ref,
        fetched_at=FETCHED_AT,
        out_dir=tmp_path,
        sleeper=None,
    )

    assert isinstance(raw, RawLineup)
    assert raw.has_lineup is False
    assert raw.home is None
    assert raw.away is None

    # Bronze se persiste igualmente (R1)
    slug = _slug_from_ref(match_ref)
    json_path, meta_path = _bronze_paths(slug, tmp_path)
    assert json_path.is_file()
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    assert doc["has_lineup"] is False


# ---------------------------------------------------------------------------
# R1, R5: test_error_red_salta_partido
# ---------------------------------------------------------------------------


def test_error_red_salta_partido(tmp_path):
    """R1 (R5): error en el transporte → warn, no lanza, RawLineup con has_lineup=False."""
    match_ref = _make_match_ref()

    def _failing_transport(url: str) -> str:
        raise ConnectionError("timeout")

    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        raw = fetch_match_lineup(
            transport=_failing_transport,
            match_ref=match_ref,
            fetched_at=FETCHED_AT,
            out_dir=tmp_path,
            sleeper=None,
        )

    assert isinstance(raw, RawLineup)
    assert raw.has_lineup is False
    assert len(w) >= 1
    assert any("transporte" in str(warning.message).lower() for warning in w)


# ---------------------------------------------------------------------------
# R4: test_cli_ingest_roster
# ---------------------------------------------------------------------------


def test_cli_ingest_roster(tmp_path):
    """R4: subcomando ingest-roster retorna exit 0 con monkeypatch de ingest_roster."""
    from src.cli import main

    fake_coverage = RosterCoverage(
        n_matches=2,
        n_with_lineup=1,
        n_teams_mapped=2,
        n_teams_discarded=0,
    )

    with patch("src.cli.ingest_roster", return_value=([], fake_coverage)):
        exit_code = main(["ingest-roster"])

    assert exit_code == 0


def test_cli_ingest_roster_fallo_devuelve_1(tmp_path):
    """R4: si ingest_roster lanza excepción, el subcomando devuelve exit 1."""
    from src.cli import main

    with patch("src.cli.ingest_roster", side_effect=RuntimeError("sin red")):
        exit_code = main(["ingest-roster"])

    assert exit_code == 1


# ---------------------------------------------------------------------------
# R4: test_subcomandos_exactos_intactos
# ---------------------------------------------------------------------------

EXPECTED_SUBCOMMANDS_F21 = frozenset(
    {
        "ingest-public",
        "build-features",
        "train",
        "predict",
        "schedule",
        "markets",
        "backtest",
        "predict-log",
        "evaluate",
        "ingest-goalscorers",
        "scorers",
        "simulate",
        "ingest-elo",
        "ingest-wiki-stats",
        "ingest-roster",       # Feature 21
        "ingest-fotmob-stats", # Feature 23
        "corners",             # Feature 24
        "count-market",        # Feature 25
    }
)


def test_subcomandos_exactos_intactos():
    """R4: el parser tiene EXACTAMENTE 18 subcomandos, los esperados sin añadidos."""
    from src.cli import build_parser

    parser = build_parser()
    # Extraer los nombres de subcomandos del parser
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "_name_parser_map"):
            subparsers_action = action
            break

    assert subparsers_action is not None, "No se encontraron subparsers en el parser"
    actual = frozenset(subparsers_action._name_parser_map.keys())
    assert actual == EXPECTED_SUBCOMMANDS_F21, (
        f"Diferencia: extra={actual - EXPECTED_SUBCOMMANDS_F21}, "
        f"faltantes={EXPECTED_SUBCOMMANDS_F21 - actual}"
    )
