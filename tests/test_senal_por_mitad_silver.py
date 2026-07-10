"""tests/test_senal_por_mitad_silver.py — Feature 32, R3: silver por-mitad.

Offline, sin red. Trazabilidad:
- test_silver_por_mitad_row   → R3 (fila por equipo/mitad con gf/ga/xg/shots)
- test_xg_null_sin_cobertura  → R3 (partido sin per-mitad → cover_xg False, xg None)
- test_antifuga_as_of         → R3 (anti-fuga date < as_of)
"""

from __future__ import annotations

from src.features.half_silver import build_silver_por_mitad, match_half_rows


def test_silver_por_mitad_row():
    """R3: match_half_rows produce 4 filas (equipo×mitad) con gf/ga/xg/shots correctos."""
    periods = {
        "FirstHalf": {"home": {"xg": 0.5, "shots": 8}, "away": {"xg": 0.3, "shots": 4}},
        "SecondHalf": {"home": {"xg": 1.6, "shots": 9}, "away": {"xg": 0.2, "shots": 3}},
    }
    goals = [  # FRA(home) marca 66 y 82 (2T); MAR(away) marca 20 (1T)
        {"minute": 20, "is_home": False, "own_goal": False},
        {"minute": 66, "is_home": True, "own_goal": False},
        {"minute": 82, "is_home": True, "own_goal": False},
    ]
    rows = match_half_rows("m1", "2026-06-16", "FRA", "MAR", periods, goals)
    assert len(rows) == 4

    fra_2t = next(r for r in rows if r["team_code"] == "FRA" and r["half"] == "2T")
    assert fra_2t["gf"] == 2
    assert fra_2t["ga"] == 0
    assert fra_2t["xg_for"] == 1.6
    assert fra_2t["xg_against"] == 0.2
    assert fra_2t["shots_for"] == 9
    assert fra_2t["cover_xg"] is True

    mar_1t = next(r for r in rows if r["team_code"] == "MAR" and r["half"] == "1T")
    assert mar_1t["gf"] == 1  # MAR marcó al 20'
    assert mar_1t["ga"] == 0
    assert mar_1t["xg_for"] == 0.3  # xg del visitante en FirstHalf


def test_xg_null_sin_cobertura():
    """R3: sin periodos per-mitad (solo minutos) → cover_xg False, xg None, gf/ga presentes."""
    goals = [{"minute": 30, "is_home": True, "own_goal": False}]
    rows = match_half_rows("m2", "2026-06-01", "ESP", "ITA", periods={}, goals=goals)
    esp_1t = next(r for r in rows if r["team_code"] == "ESP" and r["half"] == "1T")
    assert esp_1t["gf"] == 1
    assert esp_1t["cover_xg"] is False
    assert esp_1t["xg_for"] is None
    assert esp_1t["shots_for"] is None


def test_antifuga_as_of():
    """R3: build_silver_por_mitad excluye partidos con date >= as_of (anti-fuga)."""
    matches = [
        {"match_id": "a", "date": "2026-06-01", "home_code": "FRA", "away_code": "MAR",
         "periods": {}, "goals": [{"minute": 10, "is_home": True, "own_goal": False}]},
        {"match_id": "b", "date": "2026-07-09", "home_code": "FRA", "away_code": "MAR",
         "periods": {}, "goals": [{"minute": 10, "is_home": True, "own_goal": False}]},
    ]
    df = build_silver_por_mitad(matches, as_of="2026-07-01")
    assert set(df["match_id"]) == {"a"}  # 'b' es del futuro → excluido
