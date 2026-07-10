"""tests/test_senal_por_mitad_pipeline.py — Feature 32 (integración): gold half_signal.

Trazabilidad (R3/R4, integración):
- test_matches_from_goalscorers   → convierte goalscorers.csv a 'matches' (is_home, minuto)
- test_build_half_signal_shares_shrunk → gold por equipo: shares shrunk + goles/xG por mitad + n
"""

from __future__ import annotations

import pandas as pd

from src.features.half_pipeline import build_half_signal, matches_from_goalscorers
from src.models.half_signal import load_half_signal


def test_matches_from_goalscorers():
    """De goalscorers (date/home/away/team/minute) deriva matches con is_home + minuto."""
    gs = pd.DataFrame(
        [
            {"date": "2026-06-16", "home_team": "France", "away_team": "Senegal",
             "team": "France", "minute": 66, "own_goal": False},
            {"date": "2026-06-16", "home_team": "France", "away_team": "Senegal",
             "team": "Senegal", "minute": 90, "own_goal": False},
            {"date": "2026-06-10", "home_team": "France", "away_team": "Narnia",
             "team": "France", "minute": 30, "own_goal": False},  # Narnia sin código → se omite
        ]
    )
    code_map = {"France": "FRA", "Senegal": "SEN"}
    matches = matches_from_goalscorers(gs, code_map)
    assert len(matches) == 1  # el de Narnia se descarta
    m = matches[0]
    assert m["home_code"] == "FRA" and m["away_code"] == "SEN"
    assert m["periods"] == {}
    assert {"minute": 66, "is_home": True, "own_goal": False} in m["goals"]
    assert {"minute": 90, "is_home": False, "own_goal": False} in m["goals"]


def test_build_half_signal_shares_shrunk():
    """Gold por equipo: la señal (concede más en 2T) se preserva pero encoge hacia el prior."""
    silver = pd.DataFrame(
        [
            {"match_id": "m1", "team_code": "SUI", "half": "1T", "gf": 12, "ga": 3,
             "xg_for": 0.9, "xg_against": 0.3, "shots_for": 6, "shots_against": 4, "cover_xg": True},
            {"match_id": "m1", "team_code": "SUI", "half": "2T", "gf": 13, "ga": 14,
             "xg_for": 0.9, "xg_against": 0.4, "shots_for": 7, "shots_against": 3, "cover_xg": True},
            {"match_id": "m2", "team_code": "SUI", "half": "1T", "gf": 12, "ga": 4,
             "xg_for": 0.9, "xg_against": 0.3, "shots_for": 5, "shots_against": 5, "cover_xg": True},
            {"match_id": "m2", "team_code": "SUI", "half": "2T", "gf": 12, "ga": 13,
             "xg_for": 1.0, "xg_against": 0.5, "shots_for": 6, "shots_against": 4, "cover_xg": True},
        ]
    )
    gold = build_half_signal(silver, k=12, prior=0.46)
    row = gold[gold["team_code"] == "SUI"].iloc[0]
    assert row["n"] == 2  # 2 partidos distintos
    # concede casi todo en 2T (raw def_2t = 27/34 = 0.79) → shrunk entre 0.54 y 0.79
    assert row["def_2t"] > row["def_1t"]
    assert 0.54 < row["def_2t"] < 0.79
    # goles por mitad y medias de xG conservadas
    assert row["ga_2t"] == 27 and row["ga_1t"] == 7
    assert abs(row["xg_ag_2t"] - 0.45) < 1e-9  # media(0.4, 0.5)


def test_load_half_signal(tmp_path):
    """load_half_signal lee el CSV gold a dict {code: {att, def, ...}}."""
    p = tmp_path / "half_signal.csv"
    pd.DataFrame(
        [{"team_code": "FRA", "n": 15, "att_1t": 0.40, "att_2t": 0.60,
          "def_1t": 0.55, "def_2t": 0.45, "gf_1t": 11, "gf_2t": 20, "ga_1t": 8, "ga_2t": 5,
          "xg_for_1t": 0.5, "xg_for_2t": 1.6, "xg_ag_1t": 0.26, "xg_ag_2t": 0.47}]
    ).to_csv(p, index=False)
    sig = load_half_signal(p)
    assert sig["FRA"]["att"]["2T"] == 0.60
    assert sig["FRA"]["def"]["1T"] == 0.55
