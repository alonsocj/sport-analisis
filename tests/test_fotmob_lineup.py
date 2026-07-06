"""tests/test_fotmob_lineup.py — Feature 28: extractor de alineación fotmob. Offline."""

from __future__ import annotations

import json
from pathlib import Path

from src.ingestion.fotmob_lineup import (
    fetch_and_persist_lineup,
    parse_match_lineup,
)
from src.ingestion.roster import MatchRef


def _wrap(data: dict) -> str:
    return ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data) + "</script>")


def _page_with_lineup():
    return _wrap({"props": {"pageProps": {
        "general": {"homeTeam": {"name": "Paraguay"}, "awayTeam": {"name": "France"},
                    "matchTimeUTC": "2026-07-04T19:00:00.000Z"},
        "content": {"lineup": {
            "lineupType": "confirmed",
            "homeTeam": {"name": "Paraguay", "starters": [
                {"name": "GK P", "positionId": 11, "usualPlayingPositionId": 0,
                 "performance": {"rating": 6.6, "seasonRating": 7.0}},
                {"name": "ATT P", "positionId": 33, "usualPlayingPositionId": 3,
                 "performance": {"rating": 7.2, "seasonRating": 8.0}},
            ]},
            "awayTeam": {"name": "France", "starters": [
                {"name": "MID F", "positionId": 22, "usualPlayingPositionId": 2,
                 "performance": {"rating": 8.1, "seasonRating": 7.5}},
            ]},
        }},
    }}})


def test_parse_xi_ratings():
    parsed = parse_match_lineup(_page_with_lineup())
    assert parsed["lineup_type"] == "confirmed"
    assert parsed["date"] == "2026-07-04"
    assert parsed["home_name"] == "Paraguay"
    assert len(parsed["home"]) == 2
    gk = parsed["home"][0]
    assert gk.name == "GK P" and gk.usual_position_id == 0
    assert gk.season_rating == 7.0 and gk.match_rating == 6.6
    assert parsed["home"][1].season_rating == 8.0


def test_sin_lineup_no_aborta(tmp_path: Path):
    page = _wrap({"props": {"pageProps": {"content": {}}}})
    ref = MatchRef(match_id="1", page_url="/matches/x-vs-y/nolu#1",
                   home_team="X", away_team="Y", date="2026-07-05")
    raw = fetch_and_persist_lineup(lambda url: page, ref, fetched_at="2026-07-05T00:00:00+00:00",
                                   out_dir=tmp_path)
    assert raw.has_lineup is False
    assert (tmp_path / "nolu.json").is_file()  # se persiste igual (registro vacío)


def test_persiste_bronze_meta(tmp_path: Path):
    ref = MatchRef(match_id="4653842", page_url="/matches/france-vs-paraguay/1hu3vk#4653842",
                   home_team="Paraguay", away_team="France", date="2026-07-04")
    raw = fetch_and_persist_lineup(lambda url: _page_with_lineup(), ref,
                                   fetched_at="2026-07-04T20:00:00+00:00", out_dir=tmp_path)
    assert raw.has_lineup is True
    assert raw.home_code == "PAR" and raw.away_code == "FRA"
    doc = json.loads((tmp_path / "1hu3vk.json").read_text(encoding="utf-8"))
    assert doc["lineup_type"] == "confirmed" and len(doc["home"]) == 2
    meta = json.loads((tmp_path / "1hu3vk.meta.json").read_text(encoding="utf-8"))
    assert len(meta["sha256"]) == 64
    assert meta["fetched_at"] == "2026-07-04T20:00:00+00:00"  # inyectado, sin reloj


def test_subcomandos_exactos():
    from src.cli import build_parser
    sub = [a for a in build_parser()._actions if hasattr(a, "_name_parser_map")][0]
    names = set(sub._name_parser_map.keys())
    assert {"ingest-lineups", "build-lineup-strength"} <= names
