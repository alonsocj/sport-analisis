"""tests/test_lineup_view.py — Feature 31: vista de alineación + destacado. Puro, offline."""

from __future__ import annotations

import json
from pathlib import Path

from src.features.lineup_view import (
    build_lineup_view,
    find_lineup_doc,
    pick_crack,
    _norm,
)
from src.ingestion.fotmob_lineup import parse_match_lineup


def _wrap(data: dict) -> str:
    return ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data) + "</script>")


# ---------------------------------------------------------------------------
# R1 — extractor captura campos nuevos
# ---------------------------------------------------------------------------


def test_parse_captura_campos_nuevos():
    page = _wrap({"props": {"pageProps": {
        "general": {"matchTimeUTC": "2026-07-06T17:00:00.000Z"},
        "content": {"lineup": {"lineupType": "predicted",
            "homeTeam": {"name": "Spain", "starters": [
                {"name": "Lamine Yamal", "usualPlayingPositionId": 3, "positionId": 33,
                 "marketValue": 200000000, "shirtNumber": 19, "primaryTeamName": "Barcelona",
                 "age": 18, "performance": {"rating": None, "seasonRating": None}},
            ]},
            "awayTeam": {"name": "Portugal", "starters": []},
        }},
    }}})
    parsed = parse_match_lineup(page)
    p = parsed["home"][0]
    assert p.market_value == 200000000
    assert p.shirt_number == 19
    assert p.club == "Barcelona"
    assert p.age == 18


# ---------------------------------------------------------------------------
# R2/R3 — crack + goal_share
# ---------------------------------------------------------------------------


def _pl(name, pos, mv, sr=None, club=None, shirt=None):
    return {"name": name, "usual_position_id": pos, "market_value": mv,
            "season_rating": sr, "match_rating": None, "club": club, "shirt_number": shirt}


def test_pick_crack_mayor_valor():
    starters = [_pl("Keeper", 0, 5_000_000), _pl("Star", 3, 90_000_000, club="Bayern"),
                _pl("Mid", 2, 30_000_000)]
    crack = pick_crack(starters, [("Star", 0.42), ("Mid", 0.10)])
    assert crack["name"] == "Star"
    assert crack["club"] == "Bayern"
    assert crack["market_value"] == 90_000_000
    assert abs(crack["goal_share"] - 0.42) < 1e-9


def test_sin_valor_crack_none():
    starters = [_pl("A", 3, None), _pl("B", 2, None)]
    assert pick_crack(starters, []) is None


def test_goal_share_cruce_sin_acentos():
    # crack con acentos debe cruzar con scorer sin acentos (caveat F11)
    starters = [_pl("Julián Álvarez", 3, 80_000_000)]
    crack = pick_crack(starters, [("Julian Alvarez", 0.35)])
    assert crack["goal_share"] is not None
    assert abs(crack["goal_share"] - 0.35) < 1e-9
    assert _norm("Julián Álvarez") == "julian alvarez"


# ---------------------------------------------------------------------------
# R4 — build_view + find_doc
# ---------------------------------------------------------------------------


def test_build_view_orden_posicion_orientacion():
    doc = {
        "lineup_type": "predicted", "home_code": "ESP", "away_code": "POR",
        "home": [_pl("DEL1", 3, 90_000_000, shirt=9), _pl("POR1", 0, 10_000_000, shirt=1),
                 _pl("DEF1", 1, 40_000_000, shirt=4)],
        "away": [_pl("PortStar", 3, 70_000_000, shirt=7)],
    }
    # la llave pide home=POR, away=ESP (orientación INVERTIDA respecto al doc)
    view = build_lineup_view(doc, "POR", "ESP", scorers_home=[], scorers_away=[])
    # home de la vista = POR = lado 'away' del doc
    assert view["home"]["crack"]["name"] == "PortStar"
    # away de la vista = ESP; XI ordenado POR(0)→DEF(1)→DEL(3)
    esp_xi = view["away"]["xi"]
    assert [p["pos_label"] for p in esp_xi] == ["POR", "DEF", "DEL"]
    assert esp_xi[-1]["name"] == "DEL1" and esp_xi[-1]["is_crack"] is True


def test_sin_doc_none(tmp_path: Path):
    assert find_lineup_doc(tmp_path, "2026-07-06", "ESP", "POR") is None


def test_find_doc_por_fecha_y_par(tmp_path: Path):
    d = tmp_path / "lineups"
    d.mkdir()
    (d / "x.json").write_text(json.dumps({
        "date": "2026-07-06", "home_code": "POR", "away_code": "ESP",
        "home": [], "away": [],
    }), encoding="utf-8")
    # orientación invertida en la búsqueda + tolerancia ±1 día
    doc = find_lineup_doc(tmp_path, "2026-07-05", "ESP", "POR")
    assert doc is not None and doc["home_code"] == "POR"
