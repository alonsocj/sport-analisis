"""tests/test_senal_por_mitad.py — Feature 32: señal de tendencia por mitad (1T/2T).

Todos offline: __NEXT_DATA__ sintético embebido, sin red real, sin reloj.
Trazabilidad R<n> → test (ver specs/senal_por_mitad/):
- R1 ingesta per-mitad (Periods.FirstHalf/SecondHalf) + eventos de gol con minuto
- R2 asignación de mitad determinista (1T/2T/ET)
"""

from __future__ import annotations

import json

from src.ingestion.fotmob_halves import (
    attribute_goals,
    half_of,
    parse_goal_events,
    parse_periods,
)


# ---------------------------------------------------------------------------
# Helpers de test (sin red): __NEXT_DATA__ sintético
# ---------------------------------------------------------------------------


def _html(next_data: dict) -> str:
    payload = json.dumps(next_data)
    return (
        f'<html><head><script id="__NEXT_DATA__" type="application/json">'
        f"{payload}</script></head><body></body></html>"
    )


def _period(xg_h, xg_a, shots_h, shots_a):
    return {
        "stats": [
            {
                "title": "Top stats",
                "stats": [
                    {"title": "Ball possession", "stats": [40, 60]},
                    {"title": "Expected goals (xG)", "stats": [xg_h, xg_a]},
                    {"title": "Total shots", "stats": [shots_h, shots_a]},
                    {"title": "Corners", "stats": [2, 5]},
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# R2 — asignación de mitad determinista
# ---------------------------------------------------------------------------


def test_half_assignment_1t_2t_et():
    """R2: minuto → 1T (≤45), 2T (46..90), ET (>90) de forma determinista."""
    assert half_of(1) == "1T"
    assert half_of(45) == "1T"
    assert half_of(46) == "2T"
    assert half_of(90) == "2T"
    assert half_of(91) == "ET"
    assert half_of(120) == "ET"


# ---------------------------------------------------------------------------
# R1 — ingesta per-mitad (Periods.FirstHalf / SecondHalf)
# ---------------------------------------------------------------------------


def test_parse_periods_firsthalf_secondhalf():
    """R1: parse_periods extrae stats de All, FirstHalf y SecondHalf por equipo."""
    nd = {
        "props": {
            "pageProps": {
                "content": {
                    "stats": {
                        "Periods": {
                            "All": _period(1.5, 0.9, 17, 10),
                            "FirstHalf": _period(0.5, 0.3, 8, 4),
                            "SecondHalf": _period(1.0, 0.6, 9, 6),
                        }
                    }
                }
            }
        }
    }
    per = parse_periods(_html(nd))
    assert per["FirstHalf"]["home"]["xg"] == 0.5
    assert per["FirstHalf"]["away"]["shots"] == 4
    assert per["SecondHalf"]["home"]["xg"] == 1.0
    assert per["SecondHalf"]["away"]["shots"] == 6
    assert per["All"]["home"]["shots"] == 17


def test_bronze_schema_retrocompat():
    """R1: un __NEXT_DATA__ viejo con solo Periods.All no rompe; devuelve solo All."""
    nd = {
        "props": {
            "pageProps": {
                "content": {"stats": {"Periods": {"All": _period(1.2, 0.8, 14, 9)}}}
            }
        }
    }
    per = parse_periods(_html(nd))
    assert "All" in per
    assert "FirstHalf" not in per
    assert "SecondHalf" not in per
    assert per["All"]["home"]["xg"] == 1.2


def test_parse_goal_events_minutes():
    """R1: parse_goal_events extrae solo goles (minuto, is_home, own_goal), ignora otros eventos."""
    nd = {
        "props": {
            "pageProps": {
                "content": {
                    "matchFacts": {
                        "events": {
                            "events": [
                                {"type": "AddedTime", "time": 45},
                                {
                                    "type": "Goal",
                                    "time": 23,
                                    "overloadTime": None,
                                    "isHome": True,
                                    "ownGoal": None,
                                    "player": {"name": "Mbappé"},
                                },
                                {"type": "Half", "time": 45},
                                {
                                    "type": "Goal",
                                    "time": 90,
                                    "overloadTime": 2,
                                    "isHome": False,
                                    "ownGoal": True,
                                    "player": {"name": "OG"},
                                },
                                {"type": "Card", "time": 80},
                            ]
                        }
                    }
                }
            }
        }
    }
    goals = parse_goal_events(_html(nd))
    assert len(goals) == 2
    assert goals[0] == {
        "minute": 23,
        "stoppage": 0,
        "is_home": True,
        "own_goal": False,
        "player": "Mbappé",
    }
    assert goals[1]["is_home"] is False
    assert goals[1]["own_goal"] is True
    assert goals[1]["stoppage"] == 2


# ---------------------------------------------------------------------------
# R2 — orientación de goles por equipo (home/away) y mitad
# ---------------------------------------------------------------------------


def test_goal_orientation_home_away():
    """R2: attribute_goals asigna cada gol al equipo correcto (is_home) y su mitad."""
    goals = [
        {"minute": 10, "stoppage": 0, "is_home": True, "own_goal": False, "player": "x"},
        {"minute": 70, "stoppage": 0, "is_home": False, "own_goal": False, "player": "y"},
        {"minute": 95, "stoppage": 0, "is_home": True, "own_goal": False, "player": "z"},
    ]
    attributed = attribute_goals(goals, home_code="FRA", away_code="MAR")
    assert ("FRA", "1T") in attributed
    assert ("MAR", "2T") in attributed
    assert ("FRA", "ET") in attributed
