"""Pestana Knockouts de la app Streamlit (Feature 17: R1–R5; Feature 22: R1–R5).

Muestra las llaves de eliminacion del Mundial 2026 (R32 → Final) con tarjetas
compactas por fecha (1X2/avanza + boton "Ver detalle") y, al seleccionar una
llave, su pagina de detalle con sub-pestanas Prediccion / Mercados / Goleadores /
Equipos / Elo (Feature 22). Slider de peso gamma activa el factor de forma
reciente (Feature 16).

Principio de no-regresion (R2): con gamma=0 → form_factor=None → predict_match
usa el ramo v1 exacto. Las pestanas existentes no se modifican.
"""

from __future__ import annotations

import csv
import warnings
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import streamlit as st

from ..data import AppData
from ..figures import fig_1x2, fig_comparativa, fig_elo_lines, fig_heatmap
from ...markets.goals import MarketSummary, market_summary
from ...models.dixon_coles import (
    DixonColesParams,
    MatchPrediction,
    UnknownTeamError,
    predict_match,
)
from ...markets.by_half import prob_late_goal, prob_over_half, prob_team_scores
from ...models.half_signal import DEFAULT_PRIOR_1T, half_lambdas, split_lambda
from ...players.factor import AnytimeScorer, PlayerRate, compute_anytime_scorers, load_player_factor
from ...features.lineup_view import build_lineup_view, find_lineup_doc
from ...form import FormFactorFn, make_form_factor_fn

# ---------------------------------------------------------------------------
# Rutas por defecto (R1)
# ---------------------------------------------------------------------------

# F30: el tab principal de eliminatorias pasa a Round of 16 (octavos); r32 queda como
# dato histórico de training (F27). r8 = cuartos (Round of 8).
DEFAULT_KO_CSV: Path = Path("data/knockouts/r16_fixtures.csv")
DEFAULT_R8_CSV: Path = Path("data/knockouts/r8_fixtures.csv")
# F33: semifinales (Round of 4). Tab aditivo, mismo render que R16/R8.
DEFAULT_R4_CSV: Path = Path("data/knockouts/r4_fixtures.csv")
_DEFAULT_SILVER_CSV: Path = Path("data/silver/matches.csv")
_DEFAULT_ELO_CSV: Path = Path("data/gold/external_elo.csv")
_DEFAULT_PLAYER_FACTOR_PATH: Path = Path("data/gold/player_factor.csv")
_DEFAULT_LINEUPS_DIR: Path = Path("data/bronze/lineups")  # F31: bronze de alineaciones
_DEFAULT_HALF_SIGNAL_PATH: Path = Path("data/gold/half_signal.csv")  # F32: señal por mitad

# Rutas de rosters Feature 21 (R3)
_DEFAULT_ROSTERS_CSV: Path = Path("data") / "rosters" / "r32_rosters.csv"
_DEFAULT_UNAVAILABLE_CSV: Path = Path("data") / "rosters" / "r32_unavailable.csv"



# ---------------------------------------------------------------------------
# Modelo de datos (R1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnockoutFixture:
    """Llave de eliminacion del bracket (R1).

    Args:
        draw_order: Orden en el sorteo oficial.
        date: Fecha ISO YYYY-MM-DD.
        stage: Etapa del torneo (R32, R16, QF, SF, Final).
        home_code: Codigo FIFA del equipo nominal local.
        away_code: Codigo FIFA del equipo nominal visitante.
    """

    draw_order: int
    date: str
    stage: str
    home_code: str
    away_code: str


# ---------------------------------------------------------------------------
# Carga de fixtures (R1)
# ---------------------------------------------------------------------------


def load_knockout_fixtures(path: Path | str) -> list[KnockoutFixture]:
    """Carga las llaves del bracket desde el CSV de datos (R1).

    Ordena por (date, draw_order). Archivo ausente o vacio devuelve [] sin
    propagar excepcion (degradacion elegante).

    Args:
        path: Ruta al CSV con columnas draw_order, date, stage, home_code,
            away_code, source.

    Returns:
        Lista de KnockoutFixture ordenada por (date, draw_order).
    """
    p = Path(path)
    if not p.is_file():
        return []

    fixtures: list[KnockoutFixture] = []
    try:
        with p.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    fixtures.append(
                        KnockoutFixture(
                            draw_order=int(row["draw_order"]),
                            date=str(row["date"]),
                            stage=str(row["stage"]),
                            home_code=str(row["home_code"]),
                            away_code=str(row["away_code"]),
                        )
                    )
                except (KeyError, ValueError, TypeError):
                    continue
    except OSError:
        return []

    fixtures.sort(key=lambda f: (f.date, f.draw_order))
    return fixtures


# ---------------------------------------------------------------------------
# Prediccion neutral (R3)
# ---------------------------------------------------------------------------


def neutral_prediction(
    params: DixonColesParams,
    home: str,
    away: str,
    form_factor: FormFactorFn | None,
) -> dict:
    """Prediccion en sede neutral promediando ambas orientaciones (R3).

    Llama a predict_match(A, B) y predict_match(B, A), promedia las tres
    probabilidades 1X2 y renormaliza. Devuelve ademas p_adv_home: la
    probabilidad de que el equipo 'home' avance (p_home + 0.5 * p_draw).

    Con form_factor=None los multiplicadores son 1.0 → prediccion v1 exacta.

    Args:
        params: Parametros Dixon-Coles.
        home: Codigo FIFA del equipo nominal local en el bracket.
        away: Codigo FIFA del equipo nominal visitante en el bracket.
        form_factor: Callable (home, away) -> (mult_home, mult_away) o None.

    Returns:
        Dict con p_home, p_draw, p_away, p_adv_home.

    Raises:
        UnknownTeamError: Si alguno de los codigos no esta en los parametros.
    """
    pred_ab = predict_match(params, home, away, form_factor=form_factor)
    pred_ba = predict_match(params, away, home, form_factor=form_factor)

    # En pred_ba el rol se invierte: prob_home = P(away gana), prob_away = P(home gana)
    p_home_raw = (pred_ab.prob_home + pred_ba.prob_away) / 2.0
    p_draw_raw = (pred_ab.prob_draw + pred_ba.prob_draw) / 2.0
    p_away_raw = (pred_ab.prob_away + pred_ba.prob_home) / 2.0

    total = p_home_raw + p_draw_raw + p_away_raw
    if total > 0.0:
        p_home = p_home_raw / total
        p_draw = p_draw_raw / total
        p_away = p_away_raw / total
    else:
        p_home, p_draw, p_away = 1 / 3, 1 / 3, 1 / 3

    p_adv_home = p_home + 0.5 * p_draw

    return {
        "p_home": p_home,
        "p_draw": p_draw,
        "p_away": p_away,
        "p_adv_home": p_adv_home,
    }


# ---------------------------------------------------------------------------
# Helpers de roster (Feature 21: R3)
# ---------------------------------------------------------------------------


def _load_rosters(path: Path) -> dict[str, list[str]]:
    """Carga r32_rosters.csv → dict[team_code, list[scorer]] (R3).

    Retorna {} si el archivo no existe (degradación elegante).

    Args:
        path: Ruta al CSV con columnas team_code,scorer.

    Returns:
        Dict mapping team_code → list of scorer names.
    """
    if not path.is_file():
        return {}
    roster: dict[str, list[str]] = {}
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                code = (row.get("team_code") or "").strip()
                scorer = (row.get("scorer") or "").strip()
                if code and scorer:
                    roster.setdefault(code, []).append(scorer)
    except OSError:
        return {}
    return roster


def _load_unavailable(path: Path) -> dict[str, list[dict]]:
    """Carga r32_unavailable.csv → dict[team_code, list[{player, reason}]] (R3).

    Retorna {} si el archivo no existe.

    Args:
        path: Ruta al CSV con columnas team_code,player,reason.

    Returns:
        Dict mapping team_code → list of {player, reason} dicts.
    """
    if not path.is_file():
        return {}
    unavail: dict[str, list[dict]] = {}
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                code = (row.get("team_code") or "").strip()
                player = (row.get("player") or "").strip()
                reason = (row.get("reason") or "").strip()
                if code and player:
                    unavail.setdefault(code, []).append(
                        {"player": player, "reason": reason}
                    )
    except OSError:
        return {}
    return unavail


def _filter_and_renormalize(
    rates: list[PlayerRate],
    team_code: str,
    available: list[str],
) -> list[PlayerRate]:
    """Filtra PlayerRate a jugadores disponibles y renormaliza shares (R3).

    Si available está vacío o no hay match → devuelve rates sin filtrar (degradación).
    Renormaliza: share_new = share_original / sum(shares disponibles).

    Args:
        rates: Lista completa de PlayerRate (todos los equipos).
        team_code: Código FIFA del equipo a filtrar.
        available: Lista de nombres de jugadores disponibles.

    Returns:
        Lista de PlayerRate con rates de otros equipos intactos y
        el equipo indicado filtrado + renormalizado.
    """
    if not available:
        return rates
    available_set = set(available)
    team_rates = [r for r in rates if r.team_code == team_code]
    filtered = [r for r in team_rates if r.scorer in available_set]
    if not filtered:
        return rates  # sin match → no filtrar (best-effort)
    total_share = sum(r.share for r in filtered)
    if total_share <= 0.0:
        return rates
    renorm = [
        PlayerRate(
            team_code=r.team_code,
            scorer=r.scorer,
            goals_weighted=r.goals_weighted,
            share=r.share / total_share,
        )
        for r in filtered
    ]
    other_rates = [r for r in rates if r.team_code != team_code]
    return other_rates + renorm


# ---------------------------------------------------------------------------
# Corners O/U por llave (Feature 24: R5)
# ---------------------------------------------------------------------------


@st.cache_data
def _compute_corners_data(
    home: str,
    away: str,
    silver_path_str: str,
    as_of: str,
    k: int = 5,
) -> dict:
    """Calcula CornersSummary para una llave (Feature 24, R5).

    Cacheado por (home, away, silver_path_str, as_of, k). Sin datos de corners
    en el silver o silver ausente -> degrada devolviendo summary=None (R5, R6).
    No propaga excepciones: la UI muestra un aviso y sigue con los mercados de goles.

    Args:
        home: Codigo FIFA del equipo local.
        away: Codigo FIFA del equipo visitante.
        silver_path_str: Ruta absoluta al silver matches.csv.
        as_of: Fecha de corte YYYY-MM-DD (anti-fuga, R1 Feature 24).
        k: Pseudo-cuenta de shrinkage (default 5).

    Returns:
        Dict con keys:
        - "summary": CornersSummary o None (degradacion).
        - "error": str o None (None => exito).
    """
    import pandas as _pd

    from ...markets.corners import CornersConfig, corners_summary as _corners_summary

    silver_path = Path(silver_path_str)
    if not silver_path.is_file():
        return {"summary": None, "error": "no_silver"}

    try:
        matches = _pd.read_csv(silver_path)
    except Exception:  # noqa: BLE001
        return {"summary": None, "error": "read_error"}

    config = CornersConfig(k=k)
    try:
        cs = _corners_summary(matches, home, away, as_of, config)
    except Exception:  # noqa: BLE001
        return {"summary": None, "error": "compute_error"}

    # mu_global=0 => no habia datos de corners en el silver (degradacion, R6)
    if cs.mu_global == 0.0:
        return {"summary": None, "error": "no_corners_data"}

    return {"summary": cs, "error": None}


# ---------------------------------------------------------------------------
# Count O/U por llave (Feature 25: R4)
# ---------------------------------------------------------------------------


@st.cache_data
def _compute_counts_data(
    home: str,
    away: str,
    silver_path_str: str,
    as_of: str,
    stat: str,
    k: int = 5,
) -> dict:
    """Calcula CountSummary para una stat de conteo en una llave (Feature 25, R4).

    Cacheado por (home, away, silver_path_str, as_of, stat, k). Sin datos de la
    stat en el silver o silver ausente -> degrada devolviendo summary=None (R4).
    No propaga excepciones: la UI muestra un aviso y sigue.

    Args:
        home: Codigo FIFA del equipo local.
        away: Codigo FIFA del equipo visitante.
        silver_path_str: Ruta absoluta al silver matches.csv.
        as_of: Fecha de corte YYYY-MM-DD (anti-fuga, R1 Feature 25).
        stat: Clave de la estadistica ('cards', 'shots', 'sot').
        k: Pseudo-cuenta de shrinkage (default 5).

    Returns:
        Dict con keys:
        - "summary": CountSummary o None (degradacion).
        - "error": str o None (None => exito).
    """
    import pandas as _pd

    from ...markets.counts import CountConfig, count_summary as _count_summary

    silver_path = Path(silver_path_str)
    if not silver_path.is_file():
        return {"summary": None, "error": "no_silver"}

    try:
        matches = _pd.read_csv(silver_path)
    except Exception:  # noqa: BLE001
        return {"summary": None, "error": "read_error"}

    config = CountConfig(k=k)
    try:
        cs = _count_summary(matches, home, away, as_of, stat, config)
    except Exception:  # noqa: BLE001
        return {"summary": None, "error": "compute_error"}

    # mu_global=0 => no habia datos de la stat en el silver (degradacion, R4)
    if cs.mu_global == 0.0:
        return {"summary": None, "error": "no_data"}

    return {"summary": cs, "error": None}


# ---------------------------------------------------------------------------
# Análisis v1 por llave: mercados + goleadores (Feature 20: R1–R3; Feature 21: R3)
# ---------------------------------------------------------------------------


@st.cache_data
def _compute_analisis_data(
    _params: DixonColesParams,
    home: str,
    away: str,
    player_factor_path_str: str,
    top_k: int = 3,
    rosters_csv_str: str = "",
    unavailable_csv_str: str = "",
) -> dict:
    """Calcula mercados de goles y goleadores v1 para una llave (Feature 20: R1–R3; Feature 21: R3).

    Cacheado por ``(home, away, player_factor_path_str, top_k, rosters_csv_str,
    unavailable_csv_str)``; el argumento ``_params`` lleva prefijo ``_`` para quedar
    excluido del hash. Esto garantiza que mover el slider gamma no recalcula este
    panel (R3).

    Con roster: filtra no disponibles y renormaliza shares antes de
    compute_anytime_scorers. Sin roster (rosters_csv_str=""): comportamiento
    idéntico a Feature 20.

    Args:
        _params: DixonColesParams (excluido del hash de cache).
        home: FIFA code of the home team.
        away: FIFA code of the away team.
        player_factor_path_str: String path to player_factor.csv gold artifact.
        top_k: Number of top scorers to return per team.
        rosters_csv_str: String path to r32_rosters.csv; "" → sin filtro de roster.
        unavailable_csv_str: String path to r32_unavailable.csv; "" → sin bajas.

    Returns:
        Dict con keys: summary, scorers_home, scorers_away, no_player_factor,
        error, roster_map, unavail_map.
    """
    # --- Mercados (R1): market_summary llama predict_match internamente (v1) ---
    try:
        summary: MarketSummary = market_summary(_params, home, away)
    except UnknownTeamError:
        return {
            "summary": None,
            "scorers_home": None,
            "scorers_away": None,
            "no_player_factor": False,
            "error": "unknown_team",
            "roster_map": {},
            "unavail_map": {},
        }

    # --- Lambdas para goleadores (v1, form_factor=None) ---
    pred = predict_match(_params, home, away)
    lambda_home: float = pred.lambda_home
    lambda_away: float = pred.lambda_away

    # --- Cargar roster si se proporcionó (R3 F21) ---
    roster_map: dict[str, list[str]] = {}
    if rosters_csv_str:
        roster_map = _load_rosters(Path(rosters_csv_str))

    unavail_map: dict[str, list[dict]] = {}
    if unavailable_csv_str:
        unavail_map = _load_unavailable(Path(unavailable_csv_str))

    # --- Goleadores (R2 F20, R3 F21): cargar player_factor; degradar si no existe ---
    no_player_factor: bool = False
    scorers_home: list[AnytimeScorer] | None = None
    scorers_away: list[AnytimeScorer] | None = None

    pf_path = Path(player_factor_path_str)
    if not pf_path.is_file():
        no_player_factor = True
    else:
        try:
            rates: list[PlayerRate] = load_player_factor(pf_path)

            # Aplicar filtro+renormalización de roster si hay datos disponibles (R3)
            home_available = roster_map.get(home)
            away_available = roster_map.get(away)

            rates_home = (
                _filter_and_renormalize(rates, home, home_available)
                if home_available
                else rates
            )
            rates_away = (
                _filter_and_renormalize(rates, away, away_available)
                if away_available
                else rates
            )

            scorers_home = compute_anytime_scorers(
                rates_home, lambda_home, home, top_k=top_k
            )
            scorers_away = compute_anytime_scorers(
                rates_away, lambda_away, away, top_k=top_k
            )
        except FileNotFoundError:
            no_player_factor = True

    return {
        "summary": summary,
        "scorers_home": scorers_home,
        "scorers_away": scorers_away,
        "no_player_factor": no_player_factor,
        "error": None,
        "roster_map": roster_map,
        "unavail_map": unavail_map,
    }


def _render_analisis_llave(
    params: DixonColesParams,
    home: str,
    away: str,
    player_factor_path: Path,
    top_k: int = 3,
    rosters_csv: Path | None = None,
    unavailable_csv: Path | None = None,
) -> None:
    """Renderiza el panel expandible de mercados y goleadores (v1) para una llave (R1–R3 F20; R3 F21).

    El cálculo está cacheado por ``(home, away, player_factor_path_str, top_k,
    rosters_csv_str, unavailable_csv_str)`` via ``_compute_analisis_data``;
    mover el slider gamma no lo recalcula (R3).
    Si ``player_factor.csv`` no existe, omite la sección de goleadores con aviso (R2).
    Si hay roster disponible (Feature 21), muestra nota de bajas si existen (R3).

    Args:
        params: DixonColesParams del modelo Dixon-Coles.
        home: FIFA code del equipo nominal local.
        away: FIFA code del equipo nominal visitante.
        player_factor_path: Ruta al artefacto gold player_factor.csv.
        top_k: Número de goleadores top a mostrar por equipo.
        rosters_csv: Ruta al CSV de disponibles (Feature 21, R3); None → sin filtro.
        unavailable_csv: Ruta al CSV de bajas (Feature 21, R3); None → sin bajas.
    """
    rosters_csv_str = str(rosters_csv) if rosters_csv is not None else ""
    unavailable_csv_str = str(unavailable_csv) if unavailable_csv is not None else ""

    data = _compute_analisis_data(
        params,
        home,
        away,
        str(player_factor_path),
        top_k,
        rosters_csv_str,
        unavailable_csv_str,
    )

    if data.get("error") == "unknown_team":
        # El 1X2 de arriba ya mostró el aviso de equipo desconocido; no mostrar expander
        return

    summary: MarketSummary = data["summary"]
    no_player_factor: bool = data["no_player_factor"]
    scorers_home: list[AnytimeScorer] | None = data["scorers_home"]
    scorers_away: list[AnytimeScorer] | None = data["scorers_away"]
    unavail_map: dict[str, list[dict]] = data.get("unavail_map", {})

    with st.expander("Mercados y goleadores (v1)"):
        # Etiqueta v1 (R3): distingue del 1X2/P(avanza) que usa el slider gamma
        st.caption(
            "Mercados y goleadores se calculan con v1 (sin factor de forma). "
            "El 1X2 / P(avanza) de arriba sí usa el slider γ."
        )

        # --- O/U totales (R1) ---
        st.markdown("**Over/Under (goles totales)**")
        for ml in summary.totals:
            st.write(
                f"O{ml.line:.1f}: over {100 * ml.over:.1f}% | "
                f"under {100 * ml.under:.1f}%"
            )

        # --- BTTS (R1) ---
        st.write(
            f"**BTTS**: sí {100 * summary.btts_yes:.1f}% | "
            f"no {100 * summary.btts_no:.1f}%"
        )

        # --- Totales por equipo (R1) ---
        for code, team_totals in [(home, summary.home_totals), (away, summary.away_totals)]:
            st.markdown(f"*{code}* (goles)")
            for ml in team_totals:
                st.write(
                    f"O{ml.line:.1f}: over {100 * ml.over:.1f}% | "
                    f"under {100 * ml.under:.1f}%"
                )

        # --- Goleadores (R2) ---
        if no_player_factor:
            st.caption(
                "Sin datos de goleadores (player_factor.csv no encontrado). "
                "Ejecuta `ingest-goalscorers` + `build-features` para habilitarlo."
            )
            return

        st.markdown(f"**Goleadores top-{top_k}**")
        for team_code, scorers in [(home, scorers_home), (away, scorers_away)]:
            st.markdown(f"*{team_code}*")
            if scorers:
                for s in scorers:
                    st.write(f"{s.scorer}: P(marca) {100 * s.prob_score:.1f}%")
            else:
                st.caption(f"Sin datos históricos de goleadores para {team_code}.")

        # --- Nota de bajas (Feature 21, R3) ---
        for team_code in (home, away):
            bajas = unavail_map.get(team_code)
            if bajas:
                st.caption(
                    f"⚠️ Bajas {team_code}: "
                    + ", ".join(
                        f"{b['player']} ({b['reason']})" for b in bajas
                    )
                )


# ---------------------------------------------------------------------------
# Render de una llave individual (R3, R4)
# ---------------------------------------------------------------------------


def _render_llave(
    params: DixonColesParams,
    fixture: KnockoutFixture,
    form_factor: FormFactorFn | None,
) -> None:
    """Renderiza una tarjeta de llave con 1X2 y pick en sede neutral.

    Si alguno de los codigos no esta en params, la omite con aviso.

    Args:
        params: Parametros Dixon-Coles.
        fixture: Llave a renderizar.
        form_factor: Callable de forma o None.
    """
    try:
        pred = neutral_prediction(params, fixture.home_code, fixture.away_code, form_factor)
    except UnknownTeamError:
        st.caption(
            f"Sin prediccion: {fixture.home_code} o {fixture.away_code} "
            "no esta en los parametros del modelo."
        )
        return

    p_h = pred["p_home"]
    p_d = pred["p_draw"]
    p_a = pred["p_away"]
    adv = pred["p_adv_home"]

    pick = fixture.home_code if adv >= 0.5 else fixture.away_code

    with st.container(border=True):
        cols = st.columns([3, 4, 2])
        with cols[0]:
            st.markdown(
                f"**{fixture.home_code}** vs **{fixture.away_code}**"
            )
            st.caption(fixture.stage)
        with cols[1]:
            st.markdown(
                f"1: **{100 * p_h:.1f}%** | "
                f"X: **{100 * p_d:.1f}%** | "
                f"2: **{100 * p_a:.1f}%**"
            )
            st.caption(
                f"Avanza: **{fixture.home_code}** {100 * adv:.1f}% | "
                f"**{fixture.away_code}** {100 * (1 - adv):.1f}%"
            )
        with cols[2]:
            st.markdown(f"Pick: **{pick}**")


# ---------------------------------------------------------------------------
# Prediccion neutral con matriz promediada (Feature 22: R3)
# ---------------------------------------------------------------------------


def _neutral_matrix_pred(
    params: DixonColesParams,
    home: str,
    away: str,
    form_factor: FormFactorFn | None,
) -> MatchPrediction:
    """Prediccion neutral con matriz promediada y top-10 marcadores (R3 F22).

    Calcula pred_ab = predict_match(A, B, ff) y pred_ba = predict_match(B, A, ff);
    construye la matriz neutral M = (pred_ab.matrix + pred_ba.matrix.T) / 2
    renormalizada. Las probabilidades 1X2 se derivan con la misma formula que
    neutral_prediction. Los top-10 marcadores mas probables se extraen de M en
    orden descendente con desempate por coordenadas ascendentes. Construye un
    MatchPrediction sintetico compatible con fig_1x2 y fig_heatmap sin modificar
    figures.py (design.md decision 3).

    Args:
        params: DixonColesParams del modelo Dixon-Coles.
        home: Codigo FIFA del equipo nominal local en el bracket.
        away: Codigo FIFA del equipo nominal visitante.
        form_factor: Callable (home, away) -> (mult_home, mult_away) o None (v1).

    Returns:
        MatchPrediction sintetico neutral con matrix=M renormalizada,
        prob_home/draw/away neutrales, top_scores con 10 entradas en orden
        descendente y lambda promedio.

    Raises:
        UnknownTeamError: Si alguno de los codigos no esta en los parametros.
    """
    pred_ab = predict_match(params, home, away, form_factor=form_factor)
    pred_ba = predict_match(params, away, home, form_factor=form_factor)

    # Probabilidades 1X2 neutrales: misma formula que neutral_prediction (R3)
    p_home_raw = (pred_ab.prob_home + pred_ba.prob_away) / 2.0
    p_draw_raw = (pred_ab.prob_draw + pred_ba.prob_draw) / 2.0
    p_away_raw = (pred_ab.prob_away + pred_ba.prob_home) / 2.0
    total_p = p_home_raw + p_draw_raw + p_away_raw
    if total_p > 0.0:
        p_home = p_home_raw / total_p
        p_draw = p_draw_raw / total_p
        p_away = p_away_raw / total_p
    else:
        p_home = p_draw = p_away = 1.0 / 3.0

    # Matriz neutral: en pred_ba los ejes estan invertidos (filas=goles_away,
    # cols=goles_home) → transponer alinea A=filas, B=columnas (design.md R3).
    M: np.ndarray = (pred_ab.matrix + pred_ba.matrix.T) / 2.0
    total_m = float(M.sum())
    if total_m > 0.0:
        M = M / total_m

    # Top-10 marcadores en orden descendente (desempate por coordenadas ascendentes)
    n = M.shape[0]
    cells = [
        (gx, gy, float(M[gx, gy]))
        for gx in range(n)
        for gy in range(n)
    ]
    cells.sort(key=lambda c: (-c[2], c[0], c[1]))
    top10 = tuple(cells[:10])

    # Lambda promedio para compatibilidad con la interfaz de MatchPrediction
    lambda_home = (pred_ab.lambda_home + pred_ba.lambda_away) / 2.0
    lambda_away = (pred_ab.lambda_away + pred_ba.lambda_home) / 2.0

    return MatchPrediction(
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        matrix=M,
        prob_home=p_home,
        prob_draw=p_draw,
        prob_away=p_away,
        top_scores=top10,
    )


# ---------------------------------------------------------------------------
# Tarjeta compacta de llave (Feature 22: R1)
# ---------------------------------------------------------------------------


def _render_tarjeta_ko(
    params: DixonColesParams,
    fixture: KnockoutFixture,
    form_factor: FormFactorFn | None,
    state_key: str = "ko",
) -> None:
    """Tarjeta compacta de llave con 1X2/P(avanza) y boton Ver detalle (R1 F22).

    Muestra las probabilidades 1X2 y la probabilidad de avance en sede neutral.
    Un boton "Ver detalle" setea st.session_state["selected_ko"] con la tupla
    (date, home_code, away_code) de la llave seleccionada, siguiendo el patron
    del tab Calendario (design.md decision 1). Si algun codigo no esta en los
    parametros, muestra un aviso y no incluye boton.

    Args:
        params: DixonColesParams del modelo Dixon-Coles.
        fixture: Llave a renderizar.
        form_factor: Callable de forma reciente o None (v1).
    """
    try:
        pred = neutral_prediction(params, fixture.home_code, fixture.away_code, form_factor)
    except UnknownTeamError:
        with st.container(border=True):
            st.caption(
                f"Sin prediccion: {fixture.home_code} o {fixture.away_code} "
                "no esta en los parametros del modelo."
            )
        return

    p_h = pred["p_home"]
    p_d = pred["p_draw"]
    p_a = pred["p_away"]
    adv = pred["p_adv_home"]
    pick = fixture.home_code if adv >= 0.5 else fixture.away_code

    with st.container(border=True):
        cols = st.columns([3, 4, 2])
        with cols[0]:
            st.markdown(f"**{fixture.home_code}** vs **{fixture.away_code}**")
            st.caption(fixture.stage)
        with cols[1]:
            st.markdown(
                f"1: **{100 * p_h:.1f}%** | "
                f"X: **{100 * p_d:.1f}%** | "
                f"2: **{100 * p_a:.1f}%**"
            )
            st.caption(
                f"Avanza: **{fixture.home_code}** {100 * adv:.1f}% | "
                f"**{fixture.away_code}** {100 * (1 - adv):.1f}%"
            )
        with cols[2]:
            st.markdown(f"Pick: **{pick}**")
            btn_key = f"ko-det-{state_key}-{fixture.date}-{fixture.home_code}-{fixture.away_code}"
            if st.button("Ver detalle", key=btn_key):
                st.session_state[f"selected_ko_{state_key}"] = (
                    fixture.date,
                    fixture.home_code,
                    fixture.away_code,
                )


# ---------------------------------------------------------------------------
# Pagina de detalle de llave (Feature 22: R2)
# ---------------------------------------------------------------------------


def _fmt_market_value(value: int | None) -> str:
    """Formatea un valor de mercado en € legible (p.ej. 172246935 → '€172.2M')."""
    if not isinstance(value, int) or value <= 0:
        return ""
    if value >= 1_000_000:
        return f"€{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"€{value / 1_000:.0f}K"
    return f"€{value}"


def _render_alineacion_subtab(
    fixture: KnockoutFixture,
    analisis_data: dict,
    lineups_dir: Path,
) -> None:
    """Sub-pestaña Alineación: XI probable + tarjeta del jugador destacado (F31, R5)."""
    doc = find_lineup_doc(lineups_dir, fixture.date, fixture.home_code, fixture.away_code)
    if doc is None:
        st.caption(
            "Sin alineación disponible para esta llave. Ejecuta "
            "`python -m src.cli ingest-lineups` (red real) para poblarla."
        )
        return

    # Scorers (P(marca)) para la amenaza de gol del destacado; vacío si no hay player_factor.
    def _scorers_for(key: str) -> list[tuple[str, float]]:
        lst = analisis_data.get(key) or []
        return [(s.scorer, s.prob_score) for s in lst]

    view = build_lineup_view(
        doc, fixture.home_code, fixture.away_code,
        _scorers_for("scorers_home"), _scorers_for("scorers_away"),
    )
    lt = view.get("lineup_type") or ""
    lt_label = {"predicted": "XI probable", "standard": "XI confirmado",
                "lastStarting11": "último XI"}.get(lt, lt or "alineación")
    st.caption(f"Fuente: fotmob ({lt_label}). Destacado = mayor valor de mercado.")

    cols = st.columns(2)
    for col, code in ((cols[0], fixture.home_code), (cols[1], fixture.away_code)):
        side = view["home"] if code == fixture.home_code else view["away"]
        with col:
            st.markdown(f"### {code}")
            crack = side.get("crack")
            if crack:
                with st.container(border=True):
                    st.markdown(f"⭐ **{crack['name']}**")
                    meta = []
                    if crack.get("club"):
                        meta.append(crack["club"])
                    mv = _fmt_market_value(crack.get("market_value"))
                    if mv:
                        meta.append(mv)
                    if meta:
                        st.caption(" · ".join(meta))
                    if crack.get("goal_share") is not None:
                        st.write(f"⚽ P(marca): **{100 * crack['goal_share']:.1f}%**")
                    if crack.get("rating") is not None:
                        st.write(f"★ Rating fotmob: **{crack['rating']:.2f}**")
            xi = side.get("xi") or []
            if xi:
                st.markdown("**XI probable**")
                for p in xi:
                    dorsal = f"{p['shirt_number']:>2}" if p.get("shirt_number") is not None else " ·"
                    mark = " ⭐" if p.get("is_crack") else ""
                    st.write(f"`{dorsal}` {p['pos_label']} · {p['name']}{mark}")
            else:
                st.caption(f"Sin XI para {code}.")


def _load_half_signal_df(path: Path) -> dict[str, dict]:
    """Carga el gold half_signal a dict por código (o {} si no existe) para la app (F32)."""
    import pandas as pd  # noqa: PLC0415

    if not Path(path).is_file():
        return {}
    df = pd.read_csv(path)
    out: dict[str, dict] = {}
    for _, r in df.iterrows():
        out[str(r["team_code"])] = r.to_dict()
    return out


def _render_mitades_subtab(
    fixture: KnockoutFixture, params: DixonColesParams, signal: dict[str, dict]
) -> None:
    """Sub-pestaña Mitades (F32): tendencias 1T/2T por equipo + mercados por mitad."""
    h, a = fixture.home_code, fixture.away_code
    st.caption(
        "Tendencias 1T/2T y mercados por mitad (Feature 32). Reparte el λ del modelo por "
        "mitad con la señal por-equipo (ajuste por rival) o el prior de liga si falta cobertura."
    )
    if h not in signal or a not in signal:
        st.info(
            f"Sin señal por-mitad para {h} o {a} en `{_DEFAULT_HALF_SIGNAL_PATH}`. "
            "Se usará el reparto por prior de liga en los mercados."
        )

    # --- Tendencias por equipo (del gold) ---
    cols = st.columns(2)
    for col, code in zip(cols, (h, a)):
        with col:
            st.markdown(f"**{code}**")
            row = signal.get(code)
            if not row:
                st.caption("sin datos por-mitad")
                continue
            def _f(key):
                v = row.get(key)
                return "—" if v is None or (isinstance(v, float) and v != v) else f"{v:.2f}"
            st.markdown(
                f"| | 1T | 2T |\n|---|---|---|\n"
                f"| xG a favor | {_f('xg_for_1t')} | {_f('xg_for_2t')} |\n"
                f"| xG en contra | {_f('xg_ag_1t')} | {_f('xg_ag_2t')} |\n"
                f"| Goles a favor | {int(row['gf_1t'])} | {int(row['gf_2t'])} |\n"
                f"| Goles en contra | {int(row['ga_1t'])} | {int(row['ga_2t'])} |\n"
                f"\n<sub>n={int(row['n'])} partidos</sub>",
                unsafe_allow_html=True,
            )

    # --- Mercados por mitad ---
    try:
        pred = predict_match(params, h, a)
    except UnknownTeamError:
        st.caption(f"Mercados no disponibles: {h} o {a} no está en los parámetros.")
        return
    if h in signal and a in signal:
        l1h, l2h = half_lambdas(
            pred.lambda_home,
            {"1T": signal[h]["att_1t"], "2T": signal[h]["att_2t"]},
            {"1T": signal[a]["def_1t"], "2T": signal[a]["def_2t"]},
        )
        l1a, l2a = half_lambdas(
            pred.lambda_away,
            {"1T": signal[a]["att_1t"], "2T": signal[a]["att_2t"]},
            {"1T": signal[h]["def_1t"], "2T": signal[h]["def_2t"]},
        )
        reparto = "ajuste por rival"
    else:
        l1h, l2h = split_lambda(pred.lambda_home, DEFAULT_PRIOR_1T)
        l1a, l2a = split_lambda(pred.lambda_away, DEFAULT_PRIOR_1T)
        reparto = "prior de liga"

    st.markdown(f"**Mercados por mitad** <sub>(reparto: {reparto})</sub>", unsafe_allow_html=True)
    st.write(
        f"- **1T** over 0.5: {100 * prob_over_half(l1h, l1a, 0.5):.1f}%  ·  "
        f"over 1.5: {100 * prob_over_half(l1h, l1a, 1.5):.1f}%"
    )
    st.write(
        f"- **2T** over 0.5: {100 * prob_over_half(l2h, l2a, 0.5):.1f}%  ·  "
        f"over 1.5: {100 * prob_over_half(l2h, l2a, 1.5):.1f}%"
    )
    st.write(
        f"- **Marca en 2T**: {h} {100 * prob_team_scores(l2h):.1f}%  ·  "
        f"{a} {100 * prob_team_scores(l2a):.1f}%"
    )
    st.write(f"- **Gol en 76-90**: {100 * prob_late_goal(l2h, l2a, 0.42):.1f}%")


def _render_detalle_ko(
    fixture: KnockoutFixture,
    app_data: AppData,
    form_factor: FormFactorFn | None,
    player_factor_path: Path,
    rosters_csv: Path | None = None,
    unavailable_csv: Path | None = None,
    silver_csv: Path | None = None,
    lineups_dir: Path | None = None,
) -> None:
    """Pagina de detalle de una llave con 6 sub-pestanas (R2 F22; +Alineación F31).

    Sub-pestanas: Prediccion / Mercados / Goleadores / Equipos / Elo. Reusa
    figuras existentes (fig_1x2, fig_heatmap, fig_comparativa, fig_elo_lines) y
    los helpers de F20/F21 (_compute_analisis_data) sin modificar figures.py ni
    otros modulos (design.md decision 3 y 4).

    La sub-pestana Prediccion usa la matriz neutral (_neutral_matrix_pred) y
    respeta el slider gamma (R3). Los mercados y goleadores se calculan con v1
    (sin forma, cacheados por _compute_analisis_data). Degrada elegantemente si
    hay equipos desconocidos, player_factor o historial Elo ausentes (R5).
    La seccion Corners O/U usa _compute_corners_data (Feature 24, R5).

    Args:
        fixture: Llave seleccionada para mostrar en detalle.
        app_data: Estado cargado de la aplicacion.
        form_factor: Callable de forma reciente o None (v1).
        player_factor_path: Ruta al CSV de factores por jugador (F20/F21).
        rosters_csv: Ruta al CSV de jugadores disponibles (F21); None = sin filtro.
        unavailable_csv: Ruta al CSV de bajas (F21); None = sin bajas.
        silver_csv: Ruta al silver matches.csv para corners (Feature 24).
            None -> usa _DEFAULT_SILVER_CSV.
    """
    from ..data import team_profile

    _lineups_dir: Path = lineups_dir if lineups_dir is not None else _DEFAULT_LINEUPS_DIR

    # Pre-calcular datos de mercados y goleadores (cached) antes de abrir tabs
    rosters_csv_str = str(rosters_csv) if rosters_csv is not None else ""
    unavail_csv_str = str(unavailable_csv) if unavailable_csv is not None else ""
    analisis_data = _compute_analisis_data(
        app_data.params,
        fixture.home_code,
        fixture.away_code,
        str(player_factor_path),
        5,  # top_k: hasta 5 goleadores en el detalle (mas que en el expander F20)
        rosters_csv_str,
        unavail_csv_str,
    )

    with st.container(border=True):
        st.markdown(
            f"### {fixture.home_code} vs {fixture.away_code}"
            f" — {fixture.stage} ({fixture.date})"
        )

        sub_tabs = st.tabs(
            ["Predicción", "Mercados", "Goleadores", "Equipos", "Elo", "Alineación", "Mitades"]
        )

        # ------------------------------------------------------------------
        # Sub-pestaña 0: Prediccion neutral con top-10 (R3 F22)
        # ------------------------------------------------------------------
        with sub_tabs[0]:
            try:
                neutral_pred = _neutral_matrix_pred(
                    app_data.params,
                    fixture.home_code,
                    fixture.away_code,
                    form_factor,
                )
                st.plotly_chart(
                    fig_1x2(
                        neutral_pred,
                        home_name=fixture.home_code,
                        away_name=fixture.away_code,
                        home_code=fixture.home_code,
                        away_code=fixture.away_code,
                    ),
                    width="stretch",
                )
                st.plotly_chart(fig_heatmap(neutral_pred), width="stretch")
                st.markdown("**Top-10 marcadores mas probables (sede neutral)**")
                for gl_a, gl_b, prob in neutral_pred.top_scores[:10]:
                    st.write(f"{gl_a}–{gl_b}: {100 * prob:.2f}%")
            except UnknownTeamError:
                st.caption(
                    f"Sin prediccion disponible: {fixture.home_code} o "
                    f"{fixture.away_code} no esta en los parametros del modelo."
                )

        # ------------------------------------------------------------------
        # Sub-pestaña 1: Mercados v1 (F20)
        # ------------------------------------------------------------------
        with sub_tabs[1]:
            if analisis_data.get("error") == "unknown_team":
                st.caption(
                    f"Mercados no disponibles: {fixture.home_code} o "
                    f"{fixture.away_code} no esta en los parametros."
                )
            else:
                summary: MarketSummary = analisis_data["summary"]
                st.caption(
                    "Mercados calculados con v1 (sin factor de forma). "
                    "La prediccion de Prediccion si usa el slider γ."
                )
                st.markdown("**Over/Under (goles totales)**")
                for ml in summary.totals:
                    st.write(
                        f"O{ml.line:.1f}: over **{100 * ml.over:.1f}%** | "
                        f"under **{100 * ml.under:.1f}%**"
                    )
                st.write(
                    f"**BTTS**: si **{100 * summary.btts_yes:.1f}%** | "
                    f"no **{100 * summary.btts_no:.1f}%**"
                )
                st.markdown(f"**Totales {fixture.home_code}**")
                for ml in summary.home_totals:
                    st.write(
                        f"O{ml.line:.1f}: over **{100 * ml.over:.1f}%** | "
                        f"under **{100 * ml.under:.1f}%**"
                    )
                st.markdown(f"**Totales {fixture.away_code}**")
                for ml in summary.away_totals:
                    st.write(
                        f"O{ml.line:.1f}: over **{100 * ml.over:.1f}%** | "
                        f"under **{100 * ml.under:.1f}%**"
                    )

                # ----------------------------------------------------------
                # Corners O/U (Feature 24, R5)
                # ----------------------------------------------------------
                st.markdown("---")
                st.markdown("**Corners (O/U)**")
                _silver_path = silver_csv if silver_csv is not None else _DEFAULT_SILVER_CSV
                _as_of_str = str(app_data.params.as_of_date)
                corners_data = _compute_corners_data(
                    fixture.home_code,
                    fixture.away_code,
                    str(_silver_path),
                    _as_of_str,
                    k=5,
                )
                if corners_data.get("error") is not None:
                    st.caption(
                        "Sin datos de corners disponibles para este partido "
                        "(silver sin home/away_corners para date < as_of). "
                        "Se habilitara tras la fase de grupos."
                    )
                else:
                    cs = corners_data["summary"]
                    st.caption(
                        f"base = {cs.n_matches_home} partidos {fixture.home_code} / "
                        f"{cs.n_matches_away} partidos {fixture.away_code}; "
                        f"shrinkage k={cs.k} — muestra chica => tira a prior global "
                        f"mu={cs.mu_global:.1f} corners/equipo"
                    )
                    st.write(
                        f"Corners esperados: {fixture.home_code} **{cs.lambda_home:.1f}** | "
                        f"{fixture.away_code} **{cs.lambda_away:.1f}** | "
                        f"total **{cs.lambda_total:.1f}**"
                    )
                    st.markdown("*Over/Under corneres totales*")
                    for ou in cs.total_ou:
                        st.write(
                            f"O{ou.line:.1f}: over **{100 * ou.over:.1f}%** | "
                            f"under **{100 * ou.under:.1f}%**"
                        )
                    st.markdown(f"*Corners {fixture.home_code}*")
                    for ou in cs.home_ou:
                        st.write(
                            f"O{ou.line:.1f}: over **{100 * ou.over:.1f}%** | "
                            f"under **{100 * ou.under:.1f}%**"
                        )
                    st.markdown(f"*Corners {fixture.away_code}*")
                    for ou in cs.away_ou:
                        st.write(
                            f"O{ou.line:.1f}: over **{100 * ou.over:.1f}%** | "
                            f"under **{100 * ou.under:.1f}%**"
                        )

                # ----------------------------------------------------------
                # Count markets: tarjetas, tiros, SoT (Feature 25, R4)
                # ----------------------------------------------------------
                from ...markets.counts import STAT_SPECS as _STAT_SPECS

                for _stat_key in ("cards", "shots", "sot"):
                    _spec = _STAT_SPECS[_stat_key]
                    st.markdown("---")
                    st.markdown(f"**{_spec.label} (O/U)**")
                    _counts_data = _compute_counts_data(
                        fixture.home_code,
                        fixture.away_code,
                        str(_silver_path),
                        _as_of_str,
                        _stat_key,
                        k=5,
                    )
                    if _counts_data.get("error") is not None:
                        st.caption(
                            f"Sin datos de {_spec.label.lower()} disponibles para este "
                            "partido (silver sin columnas o date < as_of sin registros)."
                        )
                    else:
                        _cs = _counts_data["summary"]
                        if _cs.noisy_note:
                            st.warning(f"Nota: {_cs.noisy_note}")  # R4: aviso ruido tarjetas
                        st.caption(
                            f"base = {_cs.n_matches_home} partidos {fixture.home_code} / "
                            f"{_cs.n_matches_away} partidos {fixture.away_code}; "
                            f"shrinkage k={_cs.k} — muestra chica => prior global "
                            f"mu={_cs.mu_global:.1f} {_spec.label.lower()}/equipo"
                        )
                        st.write(
                            f"{_spec.label} esperadas: "
                            f"{fixture.home_code} **{_cs.lambda_home:.1f}** | "
                            f"{fixture.away_code} **{_cs.lambda_away:.1f}** | "
                            f"total **{_cs.lambda_total:.1f}**"
                        )
                        st.markdown(f"*Over/Under {_spec.label.lower()} totales*")
                        for _ou in _cs.total_ou:
                            st.write(
                                f"O{_ou.line:.1f}: over **{100 * _ou.over:.1f}%** | "
                                f"under **{100 * _ou.under:.1f}%**"
                            )
                        st.markdown(f"*{_spec.label} {fixture.home_code}*")
                        for _ou in _cs.home_ou:
                            st.write(
                                f"O{_ou.line:.1f}: over **{100 * _ou.over:.1f}%** | "
                                f"under **{100 * _ou.under:.1f}%**"
                            )
                        st.markdown(f"*{_spec.label} {fixture.away_code}*")
                        for _ou in _cs.away_ou:
                            st.write(
                                f"O{_ou.line:.1f}: over **{100 * _ou.over:.1f}%** | "
                                f"under **{100 * _ou.under:.1f}%**"
                            )

        # ------------------------------------------------------------------
        # Sub-pestaña 2: Goleadores con roster (F20 + F21)
        # ------------------------------------------------------------------
        with sub_tabs[2]:
            if analisis_data.get("error") == "unknown_team":
                st.caption(
                    f"Sin goleadores: {fixture.home_code} o "
                    f"{fixture.away_code} no esta en los parametros."
                )
            elif analisis_data["no_player_factor"]:
                st.caption(
                    "Sin datos de goleadores (player_factor.csv no encontrado). "
                    "Ejecuta `ingest-goalscorers` + `build-features` para habilitarlo."
                )
            else:
                scorers_home: list[AnytimeScorer] | None = analisis_data["scorers_home"]
                scorers_away: list[AnytimeScorer] | None = analisis_data["scorers_away"]
                unavail_map: dict = analisis_data.get("unavail_map", {})

                st.markdown("**Goleadores anytime por equipo**")
                for team_code, scorers in [
                    (fixture.home_code, scorers_home),
                    (fixture.away_code, scorers_away),
                ]:
                    st.markdown(f"*{team_code}*")
                    if scorers:
                        for s in scorers:
                            st.write(f"{s.scorer}: P(marca) {100 * s.prob_score:.1f}%")
                    else:
                        st.caption(f"Sin datos historicos de goleadores para {team_code}.")

                # Nota de bajas (F21)
                for team_code in (fixture.home_code, fixture.away_code):
                    bajas = unavail_map.get(team_code)
                    if bajas:
                        st.caption(
                            f"Bajas {team_code}: "
                            + ", ".join(
                                f"{b['player']} ({b['reason']})" for b in bajas
                            )
                        )

        # ------------------------------------------------------------------
        # Sub-pestaña 3: Equipos — comparativa (R2 F22)
        # ------------------------------------------------------------------
        with sub_tabs[3]:
            ph = team_profile(fixture.home_code, app_data)
            pa = team_profile(fixture.away_code, app_data)
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
            st.plotly_chart(fig_comparativa(profile_h, profile_a), width="stretch")

        # ------------------------------------------------------------------
        # Sub-pestaña 4: Elo — historial (R2 F22)
        # ------------------------------------------------------------------
        with sub_tabs[4]:
            teams_hist = [fixture.home_code, fixture.away_code]
            elo_rows = list(app_data.history_rows)
            if any(r.get("code") in teams_hist for r in elo_rows):
                st.plotly_chart(
                    fig_elo_lines(elo_rows, teams=teams_hist),
                    width="stretch",
                )
            else:
                st.caption(
                    f"Historial Elo no disponible para "
                    f"{fixture.home_code} / {fixture.away_code}."
                )

        # ------------------------------------------------------------------
        # Sub-pestaña 5: Alineación — XI probable + jugador destacado (F31, R5)
        # ------------------------------------------------------------------
        with sub_tabs[5]:
            _render_alineacion_subtab(fixture, analisis_data, _lineups_dir)

        # ------------------------------------------------------------------
        # Sub-pestaña 6: Mitades (Feature 32) — tendencias 1T/2T + mercados por mitad
        # ------------------------------------------------------------------
        with sub_tabs[6]:
            _half_signal = _load_half_signal_df(_DEFAULT_HALF_SIGNAL_PATH)
            _render_mitades_subtab(fixture, app_data.params, _half_signal)


# ---------------------------------------------------------------------------
# Render principal (R1–R4)
# ---------------------------------------------------------------------------


def render_knockouts(
    app_data: AppData,
    fixtures_csv: Path | str | None = None,
    form_builder: Callable = make_form_factor_fn,
    player_factor_path: Path | str | None = None,
    rosters_csv: Path | None = None,
    unavailable_csv: Path | None = None,
    silver_csv: Path | None = None,
    state_key: str = "ko",
    lineups_dir: Path | None = None,
) -> None:
    """Renderiza una pestana de eliminatorias con slider gamma, llaves y panel de analisis.

    F30: ``state_key`` namespacea los widgets (slider) y el session_state de detalle para
    permitir MULTIPLES tabs de KO (Round of 16, Round of 8) sin colision de IDs.

    El factor de forma se construye UNA sola vez por render (no por llave ni
    por fecha) usando form_builder inyectable, cumpliendo el gate de eficiencia
    O(1) en numero de llaves.

    Con gamma=0 se fuerza form_factor=None → rama v1 exacta de predict_match.

    Por cada llave se añade un expander "Mercados y goleadores (v1)" con el
    análisis de mercados de goles y goleadores anytime (Feature 20: R1–R4).
    El panel se cachea por (home, away, player_factor_path) y no se recalcula
    al mover el slider gamma (R3).

    Con rosters_csv/unavailable_csv (Feature 21, R3): filtra bajas y renormaliza
    shares de goleadores. Sin estos archivos → comportamiento idéntico a F20.

    Args:
        app_data: Estado cargado de la app.
        fixtures_csv: Ruta al CSV de llaves (inyectable para tests offline).
            None → usa DEFAULT_KO_CSV resuelto en tiempo de ejecucion (permite
            monkeypatch en AppTest).
        form_builder: Callable make_form_factor_fn (inyectable para tests).
        player_factor_path: Ruta al artefacto gold player_factor.csv (inyectable
            para tests). None → usa _DEFAULT_PLAYER_FACTOR_PATH en tiempo de
            ejecucion (permite monkeypatch en AppTest).
        rosters_csv: Ruta al CSV de jugadores disponibles (Feature 21, R3).
            None → usa _DEFAULT_ROSTERS_CSV en tiempo de ejecución.
        unavailable_csv: Ruta al CSV de bajas (Feature 21, R3).
            None → usa _DEFAULT_UNAVAILABLE_CSV en tiempo de ejecución.
        silver_csv: Ruta al silver matches.csv para corners (Feature 24, R5).
            None → usa _DEFAULT_SILVER_CSV en tiempo de ejecución.
    """
    # Resolver rutas en runtime (no en default args) para que monkeypatch funcione
    _fixtures_path: Path | str = fixtures_csv if fixtures_csv is not None else DEFAULT_KO_CSV
    _pf_path: Path = (
        Path(player_factor_path) if player_factor_path is not None
        else _DEFAULT_PLAYER_FACTOR_PATH
    )
    _rosters_csv: Path | None = (
        rosters_csv if rosters_csv is not None else _DEFAULT_ROSTERS_CSV
    )
    _unavailable_csv: Path | None = (
        unavailable_csv if unavailable_csv is not None else _DEFAULT_UNAVAILABLE_CSV
    )
    _silver_csv_ko: Path | None = silver_csv  # None => _render_detalle_ko usa _DEFAULT_SILVER_CSV

    # --- Slider gamma (R2) ---
    gamma: float = st.slider(
        "Peso forma (gamma)",
        min_value=0.0,
        max_value=1.0,
        value=0.2,
        step=0.05,
        help="0 = v1 puro. gamma=0.2 es el optimo medido (backtest WC: bate a v1 en "
        "log-loss y Brier). Mueve a 0 para comparar con v1.",
        key=f"gamma_{state_key}",
    )

    # --- Cargar fixtures (R1) ---
    fixtures = load_knockout_fixtures(_fixtures_path)
    if not fixtures:
        # Mensaje dinámico con la ruta REAL (no hardcodear r32; F30 usa r16/r8).
        st.warning(
            "No se encontraron llaves de eliminacion. "
            f"Verifica que exista: `{_fixtures_path}`"
        )
        return

    as_of: str = app_data.params.as_of_date

    # --- Factor de forma: UNA vez por render, no por llave (R2, gate 6) ---
    # gamma=0 → form_factor=None → predict_match usa ramo v1 exacto (no-regresion).
    # gamma>0 → se construye el callable via form_builder; si el silver esta vacio,
    #           se degrada a v1 con aviso.
    form_factor: FormFactorFn | None = None
    if gamma > 0.0:
        import pandas as pd
        from src.ingestion.teams import all_teams

        silver_df = (
            pd.read_csv(_DEFAULT_SILVER_CSV)
            if _DEFAULT_SILVER_CSV.is_file()
            else pd.DataFrame()
        )
        elo_df = (
            pd.read_csv(_DEFAULT_ELO_CSV)
            if _DEFAULT_ELO_CSV.is_file()
            else None
        )
        teams_48 = [t.code for t in all_teams()]

        if silver_df.empty:
            st.warning(
                f"No hay datos silver para gamma={gamma:.2f}; "
                "mostrando prediccion v1."
            )
        else:
            # F26: usar xG real en la ventana de forma (mide mejor que goles: backtest
            # WC semanal log-loss 0.8537->0.8491, exactitud +1.9pp). Default xG en knockouts.
            form_factor = form_builder(silver_df, as_of, elo_df, gamma, teams_48, use_xg=True)

    # --- Disclaimer as_of (R2) ---
    st.info(
        f"Probabilidades con parametros as_of_date: **{as_of}**. "
        f"Sede neutral: promedio de ambas orientaciones. "
        f"gamma = **{gamma:.2f}**."
    )

    # --- Agrupar por fecha y renderizar tarjetas compactas (R4, R1 F22) ---
    groups: dict[str, list[KnockoutFixture]] = defaultdict(list)
    for fix in fixtures:
        groups[fix.date].append(fix)

    for date in sorted(groups.keys()):
        st.subheader(date)
        for fix in groups[date]:
            _render_tarjeta_ko(app_data.params, fix, form_factor, state_key=state_key)

    # --- Detalle de llave seleccionada (R1 F22; namespaced por tab en F30) ---
    selected_ko = st.session_state.get(f"selected_ko_{state_key}")
    if selected_ko is not None:
        sel_date, sel_home, sel_away = selected_ko
        detail_fix = next(
            (
                f for f in fixtures
                if f.date == sel_date
                and f.home_code == sel_home
                and f.away_code == sel_away
            ),
            None,
        )
        if detail_fix is not None:
            _render_detalle_ko(
                detail_fix,
                app_data,
                form_factor,
                _pf_path,
                rosters_csv=_rosters_csv,
                unavailable_csv=_unavailable_csv,
                silver_csv=_silver_csv_ko,
                lineups_dir=lineups_dir if lineups_dir is not None else _DEFAULT_LINEUPS_DIR,
            )
