"""tests/test_lineup_strength.py — Feature 28: fuerza de alineación. Offline."""

from __future__ import annotations

import json
from pathlib import Path

from src.features.lineup_strength import build_lineup_strength


def _write_lineup(bronze: Path, doc: dict):
    d = bronze / "lineups"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{doc['match_id']}.json").write_text(json.dumps(doc), encoding="utf-8")


def _player(name, pos, sr):
    return {"name": name, "position_id": pos, "usual_position_id": pos,
            "is_starter": True, "match_rating": None, "season_rating": sr}


def test_fuerza_xi_att_def(tmp_path: Path):
    bronze = tmp_path / "bronze"
    _write_lineup(bronze, {
        "match_id": "m1", "date": "2026-07-04", "lineup_type": "confirmed",
        "home_code": "PAR", "away_code": "FRA",
        "home": [_player("GK", 0, 7.0), _player("ATT", 3, 8.0)],
        "away": [_player("MID", 2, 7.5)],
    })
    df = build_lineup_strength(bronze)
    par = df[df["team_code"] == "PAR"].iloc[0]
    assert par["xi_rating"] == 7.5           # (7.0 + 8.0)/2
    assert par["att_rating"] == 8.0          # GK w_att=0, ATT w_att=1 → 8.0
    assert par["def_rating"] == 7.0          # GK w_def=1, ATT w_def=0 → 7.0
    assert par["n_starters"] == 2
    assert par["lineup_type"] == "confirmed"
    fra = df[df["team_code"] == "FRA"].iloc[0]
    assert fra["xi_rating"] == 7.5 and fra["att_rating"] == 7.5  # MID reparte 0.5/0.5


def test_jugador_sin_rating_omitido(tmp_path: Path):
    bronze = tmp_path / "bronze"
    _write_lineup(bronze, {
        "match_id": "m2", "date": "2026-07-05", "lineup_type": "predicted",
        "home_code": "ARG", "away_code": "EGY",
        "home": [_player("A", 3, 8.0), _player("B", 3, None)],  # B sin rating
        "away": [],
    })
    df = build_lineup_strength(bronze)
    arg = df[df["team_code"] == "ARG"].iloc[0]
    assert arg["n_starters"] == 1 and arg["xi_rating"] == 8.0  # sólo A cuenta
    assert (df["team_code"] == "EGY").sum() == 0  # sin titulares con rating → sin fila


def test_sin_bronze_no_rompe(tmp_path: Path):
    df = build_lineup_strength(tmp_path / "no_existe")
    assert df.empty
    assert list(df.columns) == ["date", "team_code", "xi_rating", "att_rating",
                                "def_rating", "n_starters", "lineup_type"]
