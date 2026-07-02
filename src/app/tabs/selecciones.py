"""Pestana Selecciones de la app Streamlit (R10).

Muestra el ranking Elo de las 48 selecciones y una ficha detallada por equipo
con evolucion Elo, forma, fuerzas y partidos WC2026.
"""

from __future__ import annotations

import streamlit as st

from ..data import AppData, team_profile
from ..figures import fig_elo_lines, fig_ranking_elo
from ...ingestion.teams import all_teams


def render_selecciones(app_data: AppData) -> None:
    """Renderiza la pestana Selecciones (R10).

    Args:
        app_data: Estado cargado de la app.
    """
    st.subheader("Ranking Elo")

    # Ranking Elo de todas las selecciones (R10)
    if app_data.features_rows:
        st.plotly_chart(
            fig_ranking_elo(list(app_data.features_rows)),
            width="stretch",
        )
    else:
        st.warning("No hay datos de features disponibles para el ranking.")
        return

    st.divider()
    st.subheader("Ficha de Selección")

    # Selector de equipo (R10)
    teams = all_teams()
    team_codes = sorted(t.code for t in teams)
    # Mostrar como "CODE — Nombre"
    code_to_name = {t.code: t.name for t in teams}
    options = [f"{c} — {code_to_name[c]}" for c in team_codes]
    code_from_option = {f"{c} — {code_to_name[c]}": c for c in team_codes}

    selected_option = st.selectbox(
        label="Selecciona una selección",
        options=options,
        index=0,
    )

    if selected_option is None:
        return

    selected_code = code_from_option[selected_option]
    profile = team_profile(selected_code, app_data)

    # Ficha del equipo (R10)
    col_meta, col_fuerzas = st.columns(2)
    with col_meta:
        st.markdown(f"**Código FIFA:** {profile.code}")
        if profile.elo is not None:
            st.metric("Elo actual", f"{profile.elo:.1f}")
        else:
            st.caption("Elo no disponible.")

        if profile.matches_count > 0:
            st.metric("Partidos (ventana)", profile.matches_count)
            if profile.gf_ma15 is not None:
                st.metric("Goles a favor (ma15)", f"{profile.gf_ma15:.2f}")
            if profile.ga_ma15 is not None:
                st.metric("Goles en contra (ma15)", f"{profile.ga_ma15:.2f}")
        else:
            st.info(f"{selected_code} no tiene suficientes partidos recientes (matches_count = 0).")

    with col_fuerzas:
        if profile.attack is not None:
            st.metric("Fuerza ataque (Dixon-Coles)", f"{profile.attack:.3f}")
        else:
            st.caption("Fuerza ataque no disponible.")
        if profile.defense is not None:
            st.metric("Fuerza defensa (Dixon-Coles)", f"{profile.defense:.3f}")
        else:
            st.caption("Fuerza defensa no disponible.")

    st.divider()

    # Evolucion Elo (R10)
    st.markdown("**Evolución Elo**")
    if profile.history_rows:
        st.plotly_chart(
            fig_elo_lines(list(profile.history_rows), teams=[selected_code]),
            width="stretch",
        )
    else:
        st.info(f"No hay historial Elo disponible para {selected_code}.")

    # Partidos WC2026 del equipo (R10)
    st.markdown("**Partidos Mundial 2026**")
    if profile.matches:
        for m in profile.matches:
            estado = "Jugado" if m.played else "Pendiente"
            marcador = (
                f"{m.home_score}–{m.away_score}"
                if m.played and m.home_score is not None
                else "—"
            )
            st.write(
                f"- {m.date}: {m.home_name} vs {m.away_name} "
                f"[{estado}] {marcador}"
            )
    else:
        st.info(f"No hay partidos WC2026 registrados para {selected_code}.")
