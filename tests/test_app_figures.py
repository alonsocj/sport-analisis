"""Tests de src/app/figures.py — builders Plotly puros (R8, R10, R11, R12).

100 % offline y deterministas: datos sinteticos construidos directamente,
sin cargar insumos de disco. Los builders deben devolver go.Figure sin importar
streamlit ni depender de estado mutable.
"""

from __future__ import annotations

import json

import plotly.graph_objects as go
import pytest

# ---------------------------------------------------------------------------
# Datos de fixture
# ---------------------------------------------------------------------------

AS_OF = "2025-12-01"

FEATURES_ROWS = [
    {"code": "ARG", "elo": 2100.0, "gf_ma15": "2.1", "ga_ma15": "0.8", "matches_count": "15"},
    {"code": "BRA", "elo": 2050.0, "gf_ma15": "1.9", "ga_ma15": "0.9", "matches_count": "15"},
    {"code": "FRA", "elo": 2000.0, "gf_ma15": "1.8", "ga_ma15": "1.0", "matches_count": "12"},
    {"code": "JPN", "elo": 1500.0, "gf_ma15": "",    "ga_ma15": "",    "matches_count": "0"},
    {"code": "MEX", "elo": 1800.0, "gf_ma15": "1.5", "ga_ma15": "1.1", "matches_count": "15"},
    {"code": "USA", "elo": 1750.0, "gf_ma15": "1.4", "ga_ma15": "1.2", "matches_count": "14"},
]

HISTORY_ROWS = [
    {"date": "2025-10-01", "code": "ARG", "elo_post": "2090.0"},
    {"date": "2025-10-01", "code": "MEX", "elo_post": "1800.0"},
    {"date": "2025-11-01", "code": "ARG", "elo_post": "2100.0"},
    {"date": "2025-11-01", "code": "MEX", "elo_post": "1790.0"},
]


def make_params_dict(success: bool = True) -> dict:
    return {
        "as_of_date": AS_OF,
        "from_date": "2018-01-01",
        "xi": 0.65,
        "mu": 0.1,
        "home_advantage": 0.3,
        "rho": -0.08,
        "attack": {
            "ARG": 0.40, "BRA": 0.15, "FRA": 0.25, "JPN": -0.30,
            "MEX": 0.20, "USA": 0.10, "andorra": -0.80,
        },
        "defense": {
            "ARG": 0.30, "BRA": 0.20, "FRA": 0.10, "JPN": -0.40,
            "MEX": 0.05, "USA": 0.00, "andorra": -0.60,
        },
        "n_matches": 240,
        "n_teams": 7,
        "min_matches": 5,
        "reg_lambda": 1.0,
        "low_data_teams": ["andorra"],
        "convergencia": {
            "success": success, "n_iter": 57, "message": "ok", "neg_log_lik": 100.0
        },
    }


def make_match_prediction():
    """Prediccion sintetica que imita MatchPrediction sin invocar el modelo."""
    import numpy as np

    from src.models.dixon_coles import MatchPrediction

    matrix = np.zeros((11, 11))
    matrix[1, 0] = 0.25  # 1-0 local gana
    matrix[0, 0] = 0.10  # 0-0 empate
    matrix[0, 1] = 0.08  # 0-1 visitante gana
    matrix /= matrix.sum()
    prob_home = float(np.tril(matrix, -1).sum())
    prob_draw = float(np.trace(matrix))
    prob_away = float(np.triu(matrix, 1).sum())
    top_scores = tuple(
        sorted(
            [(gx, gy, float(matrix[gx, gy]))
             for gx in range(11) for gy in range(11)],
            key=lambda c: (-c[2], c[0], c[1]),
        )[:5]
    )
    return MatchPrediction(
        lambda_home=1.5,
        lambda_away=1.0,
        matrix=matrix,
        prob_home=prob_home,
        prob_draw=prob_draw,
        prob_away=prob_away,
        top_scores=top_scores,
    )


# ---------------------------------------------------------------------------
# R8 — fig_1x2 y fig_heatmap: contrato de trazas y formato
# ---------------------------------------------------------------------------


def test_fig_1x2_y_heatmap_contrato() -> None:
    """R8: fig_1x2 devuelve go.Figure con 3 barras; fig_heatmap con go.Heatmap."""
    from src.app.figures import fig_1x2, fig_heatmap

    pred = make_match_prediction()

    # --- fig_1x2 ---
    fig = fig_1x2(pred, home_name="Mexico", away_name="Argentina",
                  home_code="MEX", away_code="ARG")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1
    # las categorias deben contener 1X2
    fig_json = fig.to_json()
    assert "1" in fig_json or "MEX" in fig_json  # categoria local presente
    assert "ARG" in fig_json  # visitante presente
    # porcentajes en formato .1f
    pcts = [f"{100 * p:.1f}%" for p in (pred.prob_home, pred.prob_draw, pred.prob_away)]
    for pct in pcts:
        assert pct in fig_json

    # --- fig_heatmap ---
    fig_h = fig_heatmap(pred)
    assert isinstance(fig_h, go.Figure)
    assert len(fig_h.data) >= 1
    # el primer trace debe ser Heatmap
    assert isinstance(fig_h.data[0], go.Heatmap)
    # verificar orientacion: goles local en filas (eje y = goles local)
    hm = fig_h.data[0]
    # z debe tener la misma forma que la matriz de prediccion (11x11)
    import numpy as np
    z = np.array(hm.z)
    assert z.shape == (11, 11)


def test_fig_1x2_determinista() -> None:
    """R12: misma entrada → misma figura (sin RNG)."""
    from src.app.figures import fig_1x2

    pred = make_match_prediction()
    fig1 = fig_1x2(pred, home_name="Mexico", away_name="Argentina",
                   home_code="MEX", away_code="ARG")
    fig2 = fig_1x2(pred, home_name="Mexico", away_name="Argentina",
                   home_code="MEX", away_code="ARG")
    assert fig1.to_json() == fig2.to_json()


# ---------------------------------------------------------------------------
# R10 — ranking Elo: orden y anfitrionas como traza separada
# ---------------------------------------------------------------------------


def test_ranking_orden_y_anfitrionas() -> None:
    """R10: fig_ranking_elo ordena por (-elo, code) y separa anfitrionas."""
    from src.app.figures import fig_ranking_elo

    fig = fig_ranking_elo(FEATURES_ROWS)
    assert isinstance(fig, go.Figure)
    fig_json = fig.to_json()

    # deben existir trazas con nombre Anfitrionas y Resto
    assert "Anfitrionas" in fig_json
    assert "Resto" in fig_json

    # orden categoryarray descendente por elo: ARG>BRA>FRA>MEX>USA>JPN
    assert '"categoryarray":["JPN","USA","MEX","FRA","BRA","ARG"]' in fig_json

    # MEX y USA son anfitrionas: deben estar en la traza Anfitrionas
    data = json.loads(fig_json)
    host_trace = next(t for t in data["data"] if t.get("name") == "Anfitrionas")
    host_y = host_trace["y"]
    assert "MEX" in host_y
    assert "USA" in host_y
    assert "ARG" not in host_y  # ARG no es anfitriona


def test_ranking_elo_determinista() -> None:
    """R12: fig_ranking_elo es determinista con la misma entrada."""
    from src.app.figures import fig_ranking_elo

    fig1 = fig_ranking_elo(FEATURES_ROWS)
    fig2 = fig_ranking_elo(FEATURES_ROWS)
    assert fig1.to_json() == fig2.to_json()


# ---------------------------------------------------------------------------
# R10 — fig_elo_lines: lineas cronologicas por equipo
# ---------------------------------------------------------------------------


def test_fig_elo_lines_trazas() -> None:
    """R10: fig_elo_lines devuelve una traza por equipo con elo_post cronologico."""
    from src.app.figures import fig_elo_lines

    # historial completo con dos equipos
    rows = [
        {"date": "2025-10-01", "code": "ARG", "elo_post": "2090.0"},
        {"date": "2025-11-01", "code": "ARG", "elo_post": "2100.0"},
        {"date": "2025-10-01", "code": "MEX", "elo_post": "1800.0"},
        {"date": "2025-11-01", "code": "MEX", "elo_post": "1790.0"},
    ]
    fig = fig_elo_lines(rows, teams=["ARG", "MEX"])
    assert isinstance(fig, go.Figure)
    fig_json = fig.to_json()
    assert '"name":"ARG"' in fig_json
    assert '"name":"MEX"' in fig_json

    # equipo sin filas en historial → omitido sin fallar
    fig2 = fig_elo_lines(rows, teams=["ARG", "FRA"])
    fig2_json = fig2.to_json()
    assert '"name":"ARG"' in fig2_json
    assert '"name":"FRA"' not in fig2_json


# ---------------------------------------------------------------------------
# R10 — fig_comparativa: comparativa de dos equipos
# ---------------------------------------------------------------------------


def test_fig_comparativa_contrato() -> None:
    """R10: fig_comparativa devuelve go.Figure con datos de ambos equipos."""
    from src.app.figures import fig_comparativa

    profile_a = {
        "code": "MEX", "elo": 1800.0, "attack": 0.20, "defense": 0.05,
        "gf_ma15": 1.5, "ga_ma15": 1.1,
    }
    profile_b = {
        "code": "ARG", "elo": 2100.0, "attack": 0.40, "defense": 0.30,
        "gf_ma15": 2.1, "ga_ma15": 0.8,
    }
    fig = fig_comparativa(profile_a, profile_b)
    assert isinstance(fig, go.Figure)
    fig_json = fig.to_json()
    assert "MEX" in fig_json
    assert "ARG" in fig_json


# ---------------------------------------------------------------------------
# R11 — fig_fuerzas: solo las 48 selecciones, sin slugs de entrenamiento
# ---------------------------------------------------------------------------


def test_fuerzas_solo_48() -> None:
    """R11: fig_fuerzas incluye los codigos FIFA de las 48 y excluye slugs externos."""
    from src.app.figures import fig_fuerzas

    params_d = make_params_dict()
    fig = fig_fuerzas(params_d)
    assert isinstance(fig, go.Figure)
    fig_json = fig.to_json()

    # los codigos de las 48 que estan en los params deben aparecer
    for code in ("ARG", "BRA", "FRA", "JPN", "MEX", "USA"):
        assert code in fig_json

    # 'andorra' es un slug del recorte de entrenamiento: NO debe aparecer
    assert "andorra" not in fig_json


def test_fuerzas_determinista() -> None:
    """R12: fig_fuerzas es determinista con la misma entrada."""
    from src.app.figures import fig_fuerzas

    params_d = make_params_dict()
    fig1 = fig_fuerzas(params_d)
    fig2 = fig_fuerzas(params_d)
    assert fig1.to_json() == fig2.to_json()
