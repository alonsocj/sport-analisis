"""Entrada de la app Streamlit del proyecto Mundial 2026 (R2, R14).

Uso::

    streamlit run src/app/main.py

Responsabilidades:
- Caches st.cache_data sobre load_app_data y predict_for.
- Titulo de la app y tres pestanas de nivel superior con literales constantes.
- Captura AppInputError y muestra st.error con mensaje accionable (R2).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garantizar que la raiz del proyecto esta en sys.path tanto al ejecutar con
# `streamlit run src/app/main.py` (donde __package__ es None y los imports
# relativos fallan) como al importar como modulo desde el paquete src.app.
# Esta guarda es inocua cuando el path ya esta presente.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from src.app.data import (
    DEFAULT_ELO_HISTORY_CSV,
    DEFAULT_FEATURES_CSV,
    DEFAULT_PARAMS_PATH,
    DEFAULT_RESULTS_CSV,
    AppData,
    AppInputError,
    DixonColesParams,
    MatchPrediction,
    WcMatch,
    load_app_data,
    predict_for,
)

# ---------------------------------------------------------------------------
# Literales constantes de pestanas (R14)
# ---------------------------------------------------------------------------

TAB_CALENDARIO: str = "📅 Calendario"
TAB_SELECCIONES: str = "🏆 Selecciones"
TAB_MODELO: str = "📈 Modelo"
# F30: el tab Knockouts pasa a "Round of 16" (octavos) + se añade "Round of 8" (cuartos).
# F33: se añade "Semifinal" (Round of 4).
TAB_KNOCKOUTS: str = "🏟️ Round of 16"
TAB_ROUND8: str = "🥊 Round of 8"
TAB_SEMIFINAL: str = "🏆 Semifinal"
# F34: Final (Round of 2) + 3er puesto, con paneles de simulación Monte Carlo.
TAB_FINAL: str = "🏆 Final"

# ---------------------------------------------------------------------------
# Caches (R4: data.py queda limpio de streamlit)
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner="Cargando datos…")
def _cached_load_app_data(
    features_csv: str,
    elo_history_csv: str,
    params_path: str,
    results_csv: str,
) -> AppData:
    """Envoltura cacheada de load_app_data (clave = rutas).

    Args:
        features_csv: Ruta a team_features.csv.
        elo_history_csv: Ruta a elo_history.csv.
        params_path: Ruta al JSON de parametros.
        results_csv: Ruta a results.csv.

    Returns:
        AppData cargado.
    """
    return load_app_data(
        features_csv=features_csv,
        elo_history_csv=elo_history_csv,
        params_path=params_path,
        results_csv=results_csv,
    )


@st.cache_data(show_spinner=False)
def _cached_predict_for(
    home_code: str,
    away_code: str,
    _params: DixonColesParams,
) -> MatchPrediction | None:
    """Prediccion cacheada por (home_code, away_code) (R6).

    El parametro _params lleva prefijo _ para que st.cache_data no intente
    hashearlo (es un dataclass frozen con arrays numpy, no hasheable trivialmente).

    Args:
        home_code: Codigo FIFA del local.
        away_code: Codigo FIFA del visitante.
        _params: Parametros Dixon-Coles.

    Returns:
        MatchPrediction o None.
    """
    match = WcMatch(
        date="",
        home_name="",
        away_name="",
        home_code=home_code,
        away_code=away_code,
        home_score=None,
        away_score=None,
        played=False,
        predecible=True,
    )
    return predict_for(match, _params)


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------


def main() -> None:
    """Render principal de la app (R14)."""
    st.title("⚽ Mundial 2026 — Análisis Predictivo")

    # Cargar datos con captura de error accionable (R2)
    try:
        app_data = _cached_load_app_data(
            features_csv=str(DEFAULT_FEATURES_CSV),
            elo_history_csv=str(DEFAULT_ELO_HISTORY_CSV),
            params_path=str(DEFAULT_PARAMS_PATH),
            results_csv=str(DEFAULT_RESULTS_CSV),
        )
    except AppInputError as exc:
        st.error(str(exc))
        return  # sin pestanas de contenido (R2)

    # Siete pestanas nivel app (F30: R16 + R8; F33: Semifinal; F34: Final + 3er puesto)
    tabs = st.tabs(
        [TAB_CALENDARIO, TAB_SELECCIONES, TAB_MODELO, TAB_KNOCKOUTS, TAB_ROUND8,
         TAB_SEMIFINAL, TAB_FINAL]
    )

    with tabs[0]:
        from src.app.tabs.calendario import render_calendario
        render_calendario(app_data, _cached_predict_for)

    with tabs[1]:
        from src.app.tabs.selecciones import render_selecciones
        render_selecciones(app_data)

    with tabs[2]:
        from src.app.tabs.modelo import render_modelo
        render_modelo(app_data)

    with tabs[3]:
        # Round of 16 (octavos): usa DEFAULT_KO_CSV (r16, monkeypatcheable en tests)
        from src.app.tabs.knockouts import render_knockouts
        render_knockouts(
            app_data,
            rosters_csv=Path("data/rosters/r32_rosters.csv"),
            unavailable_csv=Path("data/rosters/r32_unavailable.csv"),
            silver_csv=Path("data/silver/matches.csv"),
            state_key="r16",
        )

    with tabs[4]:
        # Round of 8 (cuartos): fixtures r8 explícitos + session_state namespaced
        from src.app.tabs.knockouts import render_knockouts, DEFAULT_R8_CSV
        render_knockouts(
            app_data,
            fixtures_csv=DEFAULT_R8_CSV,
            rosters_csv=Path("data/rosters/r32_rosters.csv"),
            unavailable_csv=Path("data/rosters/r32_unavailable.csv"),
            silver_csv=Path("data/silver/matches.csv"),
            state_key="r8",
        )

    with tabs[5]:
        # Semifinal (Round of 4): fixtures r4 explícitos + session_state namespaced (F33)
        from src.app.tabs.knockouts import render_knockouts, DEFAULT_R4_CSV
        render_knockouts(
            app_data,
            fixtures_csv=DEFAULT_R4_CSV,
            rosters_csv=Path("data/rosters/r32_rosters.csv"),
            unavailable_csv=Path("data/rosters/r32_unavailable.csv"),
            silver_csv=Path("data/silver/matches.csv"),
            state_key="r4",
        )

    with tabs[6]:
        # Final (Round of 2) + 3er puesto con paneles de simulación Monte Carlo (F34)
        from src.app.tabs.knockouts import DEFAULT_R2_CSV, DEFAULT_R3P_CSV
        from src.app.tabs.final import render_final_tab
        render_final_tab(
            app_data,
            r2_csv=DEFAULT_R2_CSV,
            r3p_csv=DEFAULT_R3P_CSV,
            rosters_csv=Path("data/rosters/r32_rosters.csv"),
            unavailable_csv=Path("data/rosters/r32_unavailable.csv"),
            silver_csv=Path("data/silver/matches.csv"),
        )


main()
