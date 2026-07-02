"""Pestana Calendario de la app Streamlit (R3, R5–R9, Feature 4 R8).

Muestra la tira de dias con st.pills, tarjetas por partido (pendiente/jugado/
no predecible) y el detalle con sub-pestanas (Prediccion/Equipos/Historial Elo/
Mercados). La cuarta sub-pestana Mercados solo aparece en partidos predecibles.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

import streamlit as st

from ..data import (
    AppData,
    DixonColesParams,
    MatchPrediction,
    OutcomeEval,
    WcMatch,
    match_outcome_eval,
    pending_default_day,
)
from ..figures import fig_1x2, fig_comparativa, fig_elo_lines, fig_heatmap

# Literal de aviso bronze (R3)
_AVISO_INGEST_PUBLIC = (
    "No hay datos de resultados disponibles. "
    "Ejecuta primero: `python -m src.ingestion.ingest ingest-public`"
)

# Nombres de sub-pestanas de detalle (R8, Feature 4 R8)
_SUBTAB_PRED = "Predicción"
_SUBTAB_EQUIPOS = "Equipos"
_SUBTAB_ELO = "Historial Elo"
_SUBTAB_MERCADOS = "Mercados"


@st.cache_data(show_spinner=False)
def _cached_market_summary(
    home_code: str,
    away_code: str,
    _params: DixonColesParams,
) -> object:
    """Resumen de mercados cacheado por (home_code, away_code) (Feature 4 R8).

    El parametro _params lleva prefijo _ para que st.cache_data no intente
    hashearlo (mismo patron que _cached_predict_for en main.py).

    Args:
        home_code: Codigo FIFA del local.
        away_code: Codigo FIFA del visitante.
        _params: Parametros Dixon-Coles.

    Returns:
        MarketSummary o None si el calculo falla.
    """
    from src.markets.goals import market_summary
    from src.models.dixon_coles import UnknownTeamError

    try:
        return market_summary(_params, home_code, away_code)
    except UnknownTeamError:
        return None

# Abreviaturas de meses en espanol para la etiqueta de pill
_MESES_ES = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr",
    5: "may", 6: "jun", 7: "jul", 8: "ago",
    9: "sep", 10: "oct", 11: "nov", 12: "dic",
}


def _day_label(date_str: str, n: int) -> str:
    """Etiqueta para la pill de un dia: 'DD mes (n)'.

    Args:
        date_str: Fecha ISO YYYY-MM-DD.
        n: Numero de partidos en ese dia.

    Returns:
        String como '11 jun (3)'.
    """
    try:
        parts = date_str.split("-")
        month = int(parts[1])
        day = int(parts[2])
        mes = _MESES_ES.get(month, parts[1])
        return f"{day} {mes} ({n})"
    except (IndexError, ValueError):
        return f"{date_str} ({n})"


def _group_by_day(matches: tuple[WcMatch, ...]) -> dict[str, list[WcMatch]]:
    """Agrupa los partidos por fecha.

    Args:
        matches: Partidos ordenados cronologicamente.

    Returns:
        Dict de date_str -> lista de WcMatch en ese dia.
    """
    groups: dict[str, list[WcMatch]] = defaultdict(list)
    for m in matches:
        groups[m.date].append(m)
    return dict(groups)


def _render_tarjeta_pendiente(
    match: WcMatch,
    pred: MatchPrediction | None,
) -> None:
    """Tarjeta de partido pendiente (R6, R9).

    Args:
        match: Partido pendiente.
        pred: Prediccion del modelo o None si no predecible.
    """
    with st.container(border=True):
        col_teams, col_probs, col_btn = st.columns([3, 3, 1])
        with col_teams:
            home_label = (
                f"{match.home_name} ({match.home_code})"
                if match.home_code
                else match.home_name
            )
            away_label = (
                f"{match.away_name} ({match.away_code})"
                if match.away_code
                else match.away_name
            )
            st.markdown(f"**{home_label}** vs **{away_label}**")
            st.caption(match.date)

        with col_probs:
            if pred is not None:
                # 1X2 en porcentaje con 1 decimal (R6)
                st.markdown(
                    f"1: **{100 * pred.prob_home:.1f}%** | "
                    f"X: **{100 * pred.prob_draw:.1f}%** | "
                    f"2: **{100 * pred.prob_away:.1f}%**"
                )
            else:
                # no predecible (R9)
                st.caption("sin predicción")

        with col_btn:
            btn_key = f"sel-{match.date}-{match.home_name}-{match.away_name}"
            if st.button("Ver análisis", key=btn_key):
                st.session_state["selected_match"] = (
                    match.date,
                    match.home_name,
                    match.away_name,
                )


def _render_tarjeta_jugado(
    match: WcMatch,
    pred: MatchPrediction | None,
) -> None:
    """Tarjeta de partido jugado con resultado real + prediccion comparada (R7).

    Args:
        match: Partido jugado (played=True).
        pred: Prediccion del modelo o None si no predecible.
    """
    with st.container(border=True):
        col_teams, col_result, col_btn = st.columns([3, 3, 1])
        with col_teams:
            home_label = (
                f"{match.home_name} ({match.home_code})"
                if match.home_code
                else match.home_name
            )
            away_label = (
                f"{match.away_name} ({match.away_code})"
                if match.away_code
                else match.away_name
            )
            st.markdown(f"**{home_label}** vs **{away_label}**")
            st.caption(match.date)

        with col_result:
            marcador = f"**{match.home_score} – {match.away_score}**"
            if pred is not None:
                eval_result: OutcomeEval = match_outcome_eval(match, pred)
                indicador = "✅" if eval_result.acierto else "❌"
                st.markdown(
                    f"{marcador} | "
                    f"Prob desenlace ({eval_result.outcome}): "
                    f"**{100 * eval_result.prob_outcome:.1f}%** {indicador}"
                )
            else:
                st.markdown(marcador)
                st.caption("sin predicción")

        with col_btn:
            btn_key = f"sel-{match.date}-{match.home_name}-{match.away_name}"
            if st.button("Ver análisis", key=btn_key):
                st.session_state["selected_match"] = (
                    match.date,
                    match.home_name,
                    match.away_name,
                )


def _render_detalle(
    match: WcMatch,
    pred: MatchPrediction | None,
    app_data: AppData,
) -> None:
    """Detalle de partido con sub-pestanas (R8, Feature 4 R8).

    Cuando el partido es predecible, muestra cuatro sub-pestanas:
    Prediccion / Equipos / Historial Elo / Mercados. Si no es predecible,
    solo las primeras tres (sin sub-pestana Mercados).

    Args:
        match: Partido seleccionado.
        pred: Prediccion del modelo o None.
        app_data: Estado de la app para figuras de equipos.
    """
    with st.container(border=True):
        home_label = match.home_name if not match.home_code else f"{match.home_name} ({match.home_code})"
        away_label = match.away_name if not match.away_code else f"{match.away_name} ({match.away_code})"
        st.markdown(f"### {home_label} vs {away_label} — {match.date}")

        # Cuarta sub-pestana solo si el partido es predecible (Feature 4 R8)
        is_predecible = pred is not None
        tab_labels = (
            [_SUBTAB_PRED, _SUBTAB_EQUIPOS, _SUBTAB_ELO, _SUBTAB_MERCADOS]
            if is_predecible
            else [_SUBTAB_PRED, _SUBTAB_EQUIPOS, _SUBTAB_ELO]
        )
        sub_tabs = st.tabs(tab_labels)

        with sub_tabs[0]:
            # Prediccion: barras 1X2 + heatmap + top-5 (R8)
            if pred is None:
                st.caption("sin predicción disponible para este partido")
            else:
                st.plotly_chart(
                    fig_1x2(
                        pred,
                        home_name=match.home_name,
                        away_name=match.away_name,
                        home_code=match.home_code or "?",
                        away_code=match.away_code or "?",
                    ),
                    width="stretch",
                )
                st.plotly_chart(fig_heatmap(pred), width="stretch")
                # Top-5 marcadores
                st.markdown("**Top-5 marcadores más probables**")
                for gl, ga, prob in pred.top_scores[:5]:
                    st.write(f"{gl}–{ga}: {100 * prob:.2f}%")

        with sub_tabs[1]:
            # Comparativa de equipos (R8)
            if match.home_code and match.away_code:
                from ..data import team_profile
                ph = team_profile(match.home_code, app_data)
                pa = team_profile(match.away_code, app_data)
                profile_h = {
                    "code": ph.code,
                    "elo": ph.elo or 0.0,
                    "attack": ph.attack or 0.0,
                    "defense": ph.defense or 0.0,
                    "gf_ma15": ph.gf_ma15 or 0.0,
                    "ga_ma15": ph.ga_ma15 or 0.0,
                }
                profile_a = {
                    "code": pa.code,
                    "elo": pa.elo or 0.0,
                    "attack": pa.attack or 0.0,
                    "defense": pa.defense or 0.0,
                    "gf_ma15": pa.gf_ma15 or 0.0,
                    "ga_ma15": pa.ga_ma15 or 0.0,
                }
                st.plotly_chart(
                    fig_comparativa(profile_h, profile_a),
                    width="stretch",
                )
            else:
                st.caption("Comparativa no disponible: algún equipo no tiene código FIFA.")

        with sub_tabs[2]:
            # Historial Elo (R8)
            teams_hist = [
                c for c in [match.home_code, match.away_code] if c is not None
            ]
            if teams_hist:
                st.plotly_chart(
                    fig_elo_lines(list(app_data.history_rows), teams=teams_hist),
                    width="stretch",
                )
            else:
                st.caption("Historial Elo no disponible para este partido.")

        # Cuarta sub-pestana: Mercados (solo si predecible, Feature 4 R8)
        if is_predecible and match.home_code and match.away_code:
            with sub_tabs[3]:
                summary = _cached_market_summary(
                    match.home_code,
                    match.away_code,
                    app_data.params,
                )
                if summary is None:
                    st.caption("Mercados no disponibles para este partido.")
                else:
                    st.markdown("**Over/Under — Goles Totales**")
                    for ml in summary.totals:
                        st.write(
                            f"O{ml.line:.1f}: over **{100 * ml.over:.1f}%** | "
                            f"under **{100 * ml.under:.1f}%**"
                        )
                    st.markdown("**BTTS (ambos marcan)**")
                    st.write(
                        f"Sí: **{100 * summary.btts_yes:.1f}%** | "
                        f"No: **{100 * summary.btts_no:.1f}%**"
                    )
                    st.markdown(f"**Totales {match.home_code}**")
                    for ml in summary.home_totals:
                        st.write(
                            f"O{ml.line:.1f}: over **{100 * ml.over:.1f}%** | "
                            f"under **{100 * ml.under:.1f}%**"
                        )
                    st.markdown(f"**Totales {match.away_code}**")
                    for ml in summary.away_totals:
                        st.write(
                            f"O{ml.line:.1f}: over **{100 * ml.over:.1f}%** | "
                            f"under **{100 * ml.under:.1f}%**"
                        )


def render_calendario(
    app_data: AppData,
    predict_fn: Callable[[str, str, DixonColesParams], MatchPrediction | None],
) -> None:
    """Renderiza la pestana Calendario completa (R3, R5–R9).

    Args:
        app_data: Estado cargado de la app.
        predict_fn: Funcion cacheada de prediccion por (home_code, away_code, params).
    """
    # R3: sin bronze
    if not app_data.bronze_disponible:
        st.warning(_AVISO_INGEST_PUBLIC)
        return

    matches = app_data.matches
    if not matches:
        st.info("No hay partidos del Mundial 2026 en el dataset.")
        return

    # Agrupar por dia
    groups = _group_by_day(matches)
    days_sorted = sorted(groups.keys())

    # Tira de dias con st.pills (R5)
    default_day = pending_default_day(matches)
    pill_labels = [_day_label(d, len(groups[d])) for d in days_sorted]
    label_to_day = dict(zip(pill_labels, days_sorted))

    selected_label = st.pills(
        label="Selecciona un día",
        options=pill_labels,
        default=_day_label(default_day, len(groups[default_day])) if default_day else pill_labels[0],
        selection_mode="single",
    )

    # Deseleccion → re-aplica el default (R5)
    if selected_label is None:
        selected_label = (
            _day_label(default_day, len(groups[default_day]))
            if default_day
            else pill_labels[0]
        )

    selected_day = label_to_day.get(selected_label, days_sorted[0])
    day_matches = groups[selected_day]

    # Disclaimer as_of_date (R7, R12)
    st.info(
        f"Las probabilidades usan los parámetros vigentes del modelo "
        f"(as_of_date: **{app_data.params.as_of_date}**). "
        "No son predicciones congeladas pre-partido "
        "(evaluación walk-forward: feature 5)."
    )

    # Tarjetas de partidos del dia seleccionado
    for match in day_matches:
        pred: MatchPrediction | None = None
        if match.predecible and match.home_code and match.away_code:
            pred = predict_fn(match.home_code, match.away_code, app_data.params)

        if match.played:
            _render_tarjeta_jugado(match, pred)
        else:
            _render_tarjeta_pendiente(match, pred)

    # Detalle del partido seleccionado (R8)
    selected = st.session_state.get("selected_match")
    if selected is not None:
        sel_date, sel_home, sel_away = selected
        detail_match = next(
            (
                m for m in matches
                if m.date == sel_date
                and m.home_name == sel_home
                and m.away_name == sel_away
            ),
            None,
        )
        if detail_match is not None:
            detail_pred: MatchPrediction | None = None
            if detail_match.predecible and detail_match.home_code and detail_match.away_code:
                detail_pred = predict_fn(
                    detail_match.home_code,
                    detail_match.away_code,
                    app_data.params,
                )
            _render_detalle(detail_match, detail_pred, app_data)
