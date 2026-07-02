"""Builders Plotly puros para la app Streamlit (R8, R10, R11, R12).

Cada funcion devuelve go.Figure sin depender de streamlit ni de estado mutable.
Deterministas: misma entrada → misma figura (sin RNG ni reloj) (R12).

Convenciones visuales (del design.md de features 8 y 9):
- Heatmap: goles del local en filas (eje y = goles local, eje x = goles visitante).
- Porcentajes en formato .1f (R6).
- Ranking Elo: orden (-elo, code), dos trazas Anfitrionas / Resto (R10).
- Dispersión: solo las 48 selecciones; slugs del recorte excluidos (R11).
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from ..ingestion.teams import HOST_CODES, all_teams

# Conjunto de codigos FIFA de las 48 selecciones (filtro para fig_fuerzas)
_WC_CODES: frozenset[str] = frozenset(t.code for t in all_teams())


def fig_1x2(
    pred: Any,
    home_name: str,
    away_name: str,
    home_code: str,
    away_code: str,
) -> go.Figure:
    """Barras 1X2 con probabilidades del modelo (R8).

    Args:
        pred: MatchPrediction con prob_home, prob_draw, prob_away.
        home_name: Nombre canonico del equipo local.
        away_name: Nombre canonico del equipo visitante.
        home_code: Codigo FIFA del local.
        away_code: Codigo FIFA del visitante.

    Returns:
        go.Figure con una traza Bar con las tres categorias 1X2.
    """
    categories = [
        f"1 — {home_name} ({home_code})",
        "X",
        f"2 — {away_name} ({away_code})",
    ]
    probs = [pred.prob_home, pred.prob_draw, pred.prob_away]
    texts = [f"{100 * p:.1f}%" for p in probs]

    fig = go.Figure(
        go.Bar(
            x=categories,
            y=[100 * p for p in probs],
            text=texts,
            textposition="outside",
            marker_color=["#1f77b4", "#aec7e8", "#ff7f0e"],
        )
    )
    fig.update_layout(
        title=f"{home_name} ({home_code}) vs {away_name} ({away_code})",
        yaxis_title="Probabilidad (%)",
        yaxis_range=[0, 100],
        showlegend=False,
    )
    return fig


def fig_heatmap(pred: Any) -> go.Figure:
    """Heatmap de la matriz de marcadores (R8).

    Goles del local en filas (eje y), goles del visitante en columnas (eje x).
    Rango 0..max_goals determinado por el shape de la matriz.

    Args:
        pred: MatchPrediction con matrix (ndarray shape (max_goals+1, max_goals+1)).

    Returns:
        go.Figure con go.Heatmap.
    """
    import numpy as np

    matrix = np.array(pred.matrix)
    n = matrix.shape[0]
    goals = list(range(n))

    fig = go.Figure(
        go.Heatmap(
            z=matrix,
            x=goals,
            y=goals,
            colorscale="Blues",
            text=[[f"{matrix[r, c]:.3f}" for c in goals] for r in goals],
            hovertemplate="Local %{y} - %{x} Visitante<br>P = %{z:.4f}<extra></extra>",
            showscale=True,
        )
    )
    fig.update_layout(
        xaxis_title="Goles visitante",
        yaxis_title="Goles local",
        xaxis=dict(tickmode="linear"),
        yaxis=dict(tickmode="linear"),
    )
    return fig


def fig_comparativa(
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
) -> go.Figure:
    """Comparativa de metricas entre dos equipos (R10).

    Args:
        profile_a: Dict con code, elo, attack, defense, gf_ma15, ga_ma15.
        profile_b: Dict con los mismos campos.

    Returns:
        go.Figure con barras agrupadas.
    """
    metrics = ["elo", "attack", "defense", "gf_ma15", "ga_ma15"]
    labels = ["Elo", "Ataque", "Defensa", "gf_ma15", "ga_ma15"]

    vals_a = [profile_a.get(m) or 0.0 for m in metrics]
    vals_b = [profile_b.get(m) or 0.0 for m in metrics]

    code_a = profile_a.get("code", "A")
    code_b = profile_b.get("code", "B")

    fig = go.Figure()
    fig.add_trace(go.Bar(name=code_a, x=labels, y=vals_a))
    fig.add_trace(go.Bar(name=code_b, x=labels, y=vals_b))
    fig.update_layout(
        barmode="group",
        title=f"{code_a} vs {code_b} — Comparativa",
        yaxis_title="Valor",
    )
    return fig


def fig_elo_lines(
    history_rows: list[dict[str, Any]],
    teams: list[str],
) -> go.Figure:
    """Lineas de evolucion Elo por equipo (R10).

    Una traza por equipo en orden cronologico. Equipos sin filas en el historial
    se omiten sin fallar (R10).

    Args:
        history_rows: Filas del CSV elo_history (dicts con date, code, elo_post).
        teams: Lista de codigos FIFA a graficar.

    Returns:
        go.Figure con trazas Scatter por equipo.
    """
    fig = go.Figure()

    for code in teams:
        rows = sorted(
            [r for r in history_rows if r.get("code") == code],
            key=lambda r: r.get("date", ""),
        )
        if not rows:
            continue  # omitido sin fallar (R10)

        dates = [r.get("date", "") for r in rows]
        elos = []
        for r in rows:
            try:
                elos.append(float(r.get("elo_post", 0) or 0))
            except (ValueError, TypeError):
                elos.append(0.0)

        fig.add_trace(
            go.Scatter(
                x=dates,
                y=elos,
                mode="lines+markers",
                name=code,
            )
        )

    fig.update_layout(
        title="Evolucion Elo",
        xaxis_title="Fecha",
        yaxis_title="Elo",
    )
    return fig


def fig_ranking_elo(features_rows: list[dict[str, Any]]) -> go.Figure:
    """Ranking Elo horizontal con anfitrionas como traza separada (R10).

    Orden determinista (-elo, code): categoryarray explicito en eje y.
    Dos trazas fijas: 'Anfitrionas' (HOST_CODES) y 'Resto'.

    Args:
        features_rows: Filas del CSV team_features con code y elo.

    Returns:
        go.Figure con barras horizontales y categoryarray explicito.
    """
    # parsear y ordenar (-elo, code)
    rows_parsed: list[tuple[str, float]] = []
    for r in features_rows:
        code = r.get("code", "")
        try:
            elo = float(r.get("elo", 0) or 0)
        except (ValueError, TypeError):
            elo = 0.0
        rows_parsed.append((code, elo))

    rows_sorted = sorted(rows_parsed, key=lambda x: (-x[1], x[0]))

    # categoryarray: orden ascendente para el eje y (plotly: de abajo a arriba)
    # el primero en la lista es el de abajo en el grafico de barras horizontal
    category_array = [code for code, _ in rows_sorted[::-1]]  # de menor a mayor elo

    hosts = [(c, e) for c, e in rows_sorted if c in HOST_CODES]
    rest = [(c, e) for c, e in rows_sorted if c not in HOST_CODES]

    fig = go.Figure()

    # traza Anfitrionas
    fig.add_trace(
        go.Bar(
            name="Anfitrionas",
            y=[c for c, _ in hosts],
            x=[e for _, e in hosts],
            orientation="h",
            marker_color="#ff7f0e",
        )
    )

    # traza Resto
    fig.add_trace(
        go.Bar(
            name="Resto",
            y=[c for c, _ in rest],
            x=[e for _, e in rest],
            orientation="h",
            marker_color="#1f77b4",
        )
    )

    fig.update_layout(
        title="Ranking Elo",
        xaxis_title="Elo",
        barmode="overlay",
        yaxis=dict(
            categoryorder="array",
            categoryarray=category_array,
        ),
    )
    return fig


def fig_fuerzas(params_dict: dict[str, Any]) -> go.Figure:
    """Dispersion attack vs defense solo para las 48 selecciones (R11).

    Slugs del recorte de entrenamiento que no pertenecen a las 48 se excluyen.
    Orden de puntos por code ascendente (determinismo).

    Args:
        params_dict: Diccionario con claves 'attack' y 'defense' (mapas code->float).

    Returns:
        go.Figure con go.Scatter en modo markers+text.
    """
    attack: dict[str, float] = params_dict.get("attack", {})
    defense: dict[str, float] = params_dict.get("defense", {})

    codes = sorted(c for c in attack if c in _WC_CODES and c in defense)

    x_vals = [attack[c] for c in codes]
    y_vals = [defense[c] for c in codes]

    fig = go.Figure(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="markers+text",
            text=codes,
            textposition="top center",
            marker=dict(size=8),
        )
    )
    fig.update_layout(
        title="Fuerzas ataque vs defensa (48 selecciones)",
        xaxis_title="Ataque (mayor = mas gol)",
        yaxis_title="Defensa (mayor = mejor defensa)",
    )
    return fig
