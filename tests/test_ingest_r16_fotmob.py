"""tests/test_ingest_r16_fotmob.py — Feature 27: bracket KO + captura de marcador.

Todo offline: fixtures `__NEXT_DATA__`/JSON, sin red real.

Mapeo de trazabilidad:
- test_parse_bracket_rondas_y_marcadores   → R1 (parse playoff.rounds → KoMatch)
- test_ronda_ausente_no_falla              → R1 (sin rounds → lista vacía, no lanza)
- test_extractor_captura_goles             → R2 (parse_match_score + persistencia JSON)
- test_json_viejo_sin_goles_tolerante      → R2 (JSON viejo sin goles → no materializa, no crash)
- test_ko_sin_stats_persiste_con_marcador  → R3 (KO sin stats guarda marcador)
- test_write_r16_r8_fixtures_esquema       → R6 (esquema r16/r8)
- test_tbd_no_fuerza_codigo                → R6 (equipo TBD se omite)
"""

from __future__ import annotations

import json
from pathlib import Path

from src.ingestion.fotmob_ko import (
    KoMatch,
    fetch_bracket,
    parse_playoff_bracket,
    write_ko_fixtures,
)
from src.ingestion.fotmob_stats import (
    fetch_and_persist,
    parse_match_score,
)
from src.ingestion.roster import MatchRef


# ---------------------------------------------------------------------------
# Fixtures sintéticos
# ---------------------------------------------------------------------------


def _match(home, away, hg, ag, mid, slug, finished=True, date="2026-06-29"):
    return {
        "matchId": mid,
        "pageUrl": f"/matches/{home}-vs-{away}/{slug}#{mid}",
        "home": {"name": home, "shortName": home[:3].upper(), "score": hg},
        "away": {"name": away, "shortName": away[:3].upper(), "score": ag},
        "status": {"finished": finished, "started": finished, "utcTime": f"{date}T18:30:00.000Z"},
    }


def _bracket_next_data():
    """playoff.rounds: R32 (1 partido FIN) + R16 (1 FIN + 1 TBD) + QF (1 TBD)."""
    return {
        "props": {
            "pageProps": {
                "playoff": {
                    "rounds": [
                        {"matchups": [{"matches": [_match("Germany", "Paraguay", 1, 1, "4653703", "aaa111", date="2026-06-29")]}]},
                        {"matchups": [
                            {"matches": [_match("Paraguay", "France", 0, 1, "4653842", "bbb222", date="2026-07-04")]},
                            {"matches": [{
                                "matchId": "0", "pageUrl": "",
                                "home": {"name": "Winner QF 1", "score": None},
                                "away": {"name": "Winner QF 2", "score": None},
                                "status": {"finished": False, "started": False, "utcTime": "2026-07-06T17:00:00.000Z"},
                            }]},
                        ]},
                        {"matchups": [{"matches": [{
                            "matchId": "4653851", "pageUrl": "/matches/france-vs-morocco/ccc333#4653851",
                            "home": {"name": "France", "score": None},
                            "away": {"name": "Morocco", "score": None},
                            "status": {"finished": False, "started": False, "utcTime": "2026-07-09T18:00:00.000Z"},
                        }]}]},
                    ]
                }
            }
        }
    }


def _wrap_next_data(data: dict) -> str:
    """Envuelve un dict en el HTML con el script __NEXT_DATA__ que fotmob emite."""
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(data)
        + "</script></body></html>"
    )


# ---------------------------------------------------------------------------
# R1 — bracket
# ---------------------------------------------------------------------------


def test_parse_bracket_rondas_y_marcadores():
    bracket = parse_playoff_bracket(_bracket_next_data())
    assert len(bracket) == 4  # 1 R32 + 2 R16 + 1 QF

    r32 = [k for k in bracket if k.round_ordinal == 1]
    assert len(r32) == 1
    ger = r32[0]
    assert ger.stage == "R32"
    assert (ger.home_code, ger.away_code) == ("GER", "PAR")
    assert (ger.home_goals, ger.away_goals) == (1, 1)
    assert ger.finished is True
    assert ger.match_id == "4653703"
    assert ger.slug == "aaa111"

    r16 = [k for k in bracket if k.round_ordinal == 2]
    assert len(r16) == 2
    fin = [k for k in r16 if k.finished][0]
    assert (fin.home_code, fin.away_code, fin.home_goals, fin.away_goals) == ("PAR", "FRA", 0, 1)
    tbd = [k for k in r16 if not k.finished][0]
    assert tbd.home_code is None and tbd.away_code is None  # "Winner QF x" no mapea

    qf = [k for k in bracket if k.round_ordinal == 3][0]
    assert qf.stage == "QF"
    assert (qf.home_code, qf.away_code) == ("FRA", "MAR")


def test_ronda_ausente_no_falla():
    assert parse_playoff_bracket({}) == []
    assert parse_playoff_bracket({"props": {"pageProps": {"playoff": {"rounds": []}}}}) == []
    # fetch_bracket con HTML sin __NEXT_DATA__ → lista vacía, sin lanzar
    assert fetch_bracket(lambda url: "<html>no next data</html>") == []


def test_fetch_bracket_transporte_inyectable():
    html = _wrap_next_data(_bracket_next_data())
    bracket = fetch_bracket(lambda url: html)
    assert len(bracket) == 4
    assert {k.stage for k in bracket} == {"R32", "R16", "QF"}


# ---------------------------------------------------------------------------
# R2 — marcador
# ---------------------------------------------------------------------------


def test_extractor_captura_goles(tmp_path: Path):
    # Página con marcador en header.teams + fecha en general
    page = _wrap_next_data({
        "props": {"pageProps": {
            "general": {"homeTeam": {"name": "Paraguay"}, "awayTeam": {"name": "France"},
                        "matchTimeUTC": "2026-07-04T19:00:00.000Z"},
            "header": {"teams": [{"score": 0}, {"score": 1}], "status": {"scoreStr": "0 - 1"}},
            "content": {"stats": {"Periods": {"All": {"stats": []}}}},
        }}
    })
    assert parse_match_score(page) == (0, 1)

    ref = MatchRef(match_id="4653842", page_url="/matches/france-vs-paraguay/bbb222#4653842",
                   home_team="Paraguay", away_team="France", date="2026-07-04")
    raw = fetch_and_persist(lambda url: page, ref, fetched_at="2026-07-04T20:00:00+00:00",
                            out_dir=tmp_path)
    assert (raw.home_goals, raw.away_goals) == (0, 1)
    doc = json.loads((tmp_path / "bbb222.json").read_text(encoding="utf-8"))
    assert doc["home_goals"] == 0 and doc["away_goals"] == 1


def test_json_viejo_sin_goles_tolerante(tmp_path: Path):
    # parse_match_score sobre página sin header.teams → (None, None), sin crash
    page = _wrap_next_data({"props": {"pageProps": {"header": {}}}})
    assert parse_match_score(page) == (None, None)


def test_score_ignora_bool():
    # bool es subclase de int; no debe colarse como marcador
    page = _wrap_next_data({"props": {"pageProps": {"header": {"teams": [{"score": True}, {"score": 2}]}}}})
    assert parse_match_score(page) == (None, 2)


# ---------------------------------------------------------------------------
# R3 — KO sin stats persiste con marcador
# ---------------------------------------------------------------------------


def test_ko_sin_stats_persiste_con_marcador(tmp_path: Path):
    # Página sin stats (Periods.All.stats vacío) pero con marcador; override desde bracket
    page = _wrap_next_data({
        "props": {"pageProps": {
            "general": {"homeTeam": {"name": "Canada"}, "awayTeam": {"name": "Morocco"},
                        "matchTimeUTC": "2026-07-04T15:00:00.000Z"},
            "header": {"teams": [{"score": 0}, {"score": 3}]},
            "content": {"stats": {}},
        }}
    })
    ref = MatchRef(match_id="4653843", page_url="/matches/canada-vs-morocco/ddd444#4653843",
                   home_team="Canada", away_team="Morocco", date="2026-07-04")
    raw = fetch_and_persist(lambda url: page, ref, fetched_at="2026-07-04T20:00:00+00:00",
                            out_dir=tmp_path, home_goals=0, away_goals=3)
    assert raw.has_stats is False
    assert (raw.home_goals, raw.away_goals) == (0, 3)
    doc = json.loads((tmp_path / "ddd444.json").read_text(encoding="utf-8"))
    assert doc["home_goals"] == 0 and doc["away_goals"] == 3 and doc["has_stats"] is False


# ---------------------------------------------------------------------------
# R6 — fixtures
# ---------------------------------------------------------------------------


def test_write_r16_r8_fixtures_esquema(tmp_path: Path):
    bracket = parse_playoff_bracket(_bracket_next_data())
    written = write_ko_fixtures(bracket, tmp_path)
    # F33: el writer emite además la etapa SF (r4). F34: emite también Final (r2) y
    # 3er puesto (r3p). El bracket de muestra no tiene esas etapas → se escriben con
    # solo el header (cero filas).
    assert set(written) == {"R16", "QF", "SF", "Final", "3P"}

    r16 = (tmp_path / "r16_fixtures.csv").read_text(encoding="utf-8").splitlines()
    assert r16[0] == "draw_order,date,stage,home_code,away_code,source"
    # sólo el partido R16 con ambos códigos resueltos (PAR-FRA); el TBD se omite
    assert len(r16) == 2
    assert r16[1] == "1,2026-07-04,R16,PAR,FRA,fotmob_official"

    r8 = (tmp_path / "r8_fixtures.csv").read_text(encoding="utf-8").splitlines()
    assert r8[0] == "draw_order,date,stage,home_code,away_code,source"
    assert r8[1] == "1,2026-07-09,QF,FRA,MAR,fotmob_official"

    # F33: r4 existe con header pero sin filas (no hay SF en la muestra)
    r4 = (tmp_path / "r4_fixtures.csv").read_text(encoding="utf-8").splitlines()
    assert r4[0] == "draw_order,date,stage,home_code,away_code,source"
    assert len(r4) == 1


def test_write_sf_fixture(tmp_path: Path):
    """F33: un KoMatch de SF (ambos códigos resueltos) → fila en r4_fixtures.csv."""
    sf = KoMatch(round_ordinal=4, stage="SF", home_name="France", away_name="Spain",
                 home_code="FRA", away_code="ESP", home_goals=None, away_goals=None,
                 match_id="0", slug="", page_url="", utc_time="", date="2026-07-14",
                 finished=False, started=False)
    written = write_ko_fixtures([sf], tmp_path)
    assert "SF" in written
    r4 = (tmp_path / "r4_fixtures.csv").read_text(encoding="utf-8").splitlines()
    assert r4[0] == "draw_order,date,stage,home_code,away_code,source"
    assert r4[1] == "1,2026-07-14,SF,FRA,ESP,fotmob_official"


def test_tbd_no_fuerza_codigo(tmp_path: Path):
    # Un bracket sólo con TBD → CSV con header y cero filas (no inventa códigos)
    tbd = KoMatch(round_ordinal=2, stage="R16", home_name="Winner A", away_name="Winner B",
                  home_code=None, away_code=None, home_goals=None, away_goals=None,
                  match_id="0", slug="", page_url="", utc_time="", date="2026-07-06",
                  finished=False, started=False)
    write_ko_fixtures([tbd], tmp_path)
    r16 = (tmp_path / "r16_fixtures.csv").read_text(encoding="utf-8").splitlines()
    assert len(r16) == 1  # sólo header
