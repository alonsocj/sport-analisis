"""src/app/tabs/final.py — Pestaña Final + 3er puesto (Feature 34, R9).

Reúne DOS bloques bajo un solo tab:
- 🏆 Final (``state_key='r2'``): detalle KO estándar + panel de simulación Monte Carlo.
- 🥉 Tercer puesto (``state_key='r3p'``): detalle KO + panel de simulación con la
  amortiguación dead-rubber activada (partido de trámite, R3).

El detalle KO reutiliza ``render_knockouts`` (sin cambios). El panel de simulación llama a
``simulation.match_sim.simulate_fixture`` para el cruce del CSV y muestra P(ganador), reparto
90'/prórroga/penales, marcador modal, top marcadores y mercados. Todo offline.
"""

from __future__ import annotations

import csv
from pathlib import Path

import streamlit as st

from src.app.data import AppData
from src.app.tabs.knockouts import (
    DEFAULT_R2_CSV,
    DEFAULT_R3P_CSV,
    render_knockouts,
)
from src.models.dead_rubber import DeadRubber
from src.simulation.match_sim import MatchSimResult, simulate_fixture

# n de la simulación del panel (rápido y con error MC pequeño).
APP_SIM_N: int = 20_000
APP_SIM_SEED: int = 42


def _first_fixture(path: Path) -> tuple[str, str] | None:
    """Primer cruce resuelto (home_code, away_code) de un CSV de fixtures, o None."""
    path = Path(path)
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            home = (row.get("home_code") or "").strip()
            away = (row.get("away_code") or "").strip()
            if home and away:
                return home, away
    return None


def _run_sim(
    app_data: AppData,
    home: str,
    away: str,
    dead_rubber: DeadRubber | None,
) -> MatchSimResult:
    """Ejecuta la simulación del cruce con los parámetros de la app (base DC)."""
    return simulate_fixture(
        home,
        away,
        app_data.params,
        n=APP_SIM_N,
        seed=APP_SIM_SEED,
        dead_rubber=dead_rubber,
    )


def render_sim_panel(
    app_data: AppData,
    fixtures_csv: Path,
    *,
    dead_rubber: DeadRubber | None = None,
) -> None:
    """Panel de simulación Monte Carlo de un cruce fijo (R9)."""
    st.markdown("#### 🎲 Simulación Monte Carlo")
    if dead_rubber is not None:
        st.markdown(
            "_Amortiguación de motivación del 3er puesto (**dead-rubber**) activa: "
            "ventaja del favorito diluida + partido más abierto._"
        )

    pair = _first_fixture(Path(fixtures_csv))
    if pair is None:
        st.info("Cruce pendiente: se activará cuando la ingesta fije el enfrentamiento.")
        return

    home, away = pair
    res = _run_sim(app_data, home, away, dead_rubber)

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Gana {res.home}", f"{100 * res.p_home:.1f}%")
    c2.metric("Empate→ET→pen", f"{100 * (res.p_et + res.p_pens):.1f}%")
    c3.metric(f"Gana {res.away}", f"{100 * res.p_away:.1f}%")

    mh, ma = res.modal_score
    st.markdown(
        f"**Marcador modal 90':** {res.home} {mh}–{ma} {res.away}  ·  "
        f"**E[goles]** {res.e_goals:.2f}  ·  "
        f"camino 90' {100 * res.p_reg:.0f}% / prórroga {100 * res.p_et:.0f}% / "
        f"penales {100 * res.p_pens:.0f}%"
    )

    rows = [
        {"Marcador (90')": f"{h}–{a}", "Prob.": f"{100 * p:.1f}%"}
        for (h, a), p in res.top_scores
    ]
    st.table(rows)

    m = res.markets
    st.caption(
        f"Mercados 90' — O1.5 {100 * m['over_1.5']:.0f}%  ·  O2.5 {100 * m['over_2.5']:.0f}%  ·  "
        f"O3.5 {100 * m['over_3.5']:.0f}%  ·  BTTS {100 * m['btts']:.0f}%  "
        f"(n={res.n}, error MC ≤ {100 * max(res.std_err.values()):.2f} pp)"
    )


def render_final_tab(
    app_data: AppData,
    *,
    r2_csv: Path | None = None,
    r3p_csv: Path | None = None,
    rosters_csv: Path | None = None,
    unavailable_csv: Path | None = None,
    silver_csv: Path | None = None,
) -> None:
    """Renderiza el tab Final con los bloques Final (r2) y 3er puesto (r3p) (R9)."""
    _r2 = r2_csv if r2_csv is not None else DEFAULT_R2_CSV
    _r3p = r3p_csv if r3p_csv is not None else DEFAULT_R3P_CSV

    # --- Bloque Final ---
    st.markdown("### 🏆 Final")
    render_knockouts(
        app_data,
        fixtures_csv=_r2,
        rosters_csv=rosters_csv,
        unavailable_csv=unavailable_csv,
        silver_csv=silver_csv,
        state_key="r2",
    )
    render_sim_panel(app_data, _r2, dead_rubber=None)

    st.divider()

    # --- Bloque 3er puesto (dead-rubber) ---
    st.markdown("### 🥉 Tercer puesto")
    render_knockouts(
        app_data,
        fixtures_csv=_r3p,
        rosters_csv=rosters_csv,
        unavailable_csv=unavailable_csv,
        silver_csv=silver_csv,
        state_key="r3p",
    )
    render_sim_panel(app_data, _r3p, dead_rubber=DeadRubber())
