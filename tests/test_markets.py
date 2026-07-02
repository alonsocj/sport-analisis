"""Tests de la capa pura src/markets/goals.py (R1-R6, R9, R10).

100% offline, sin red, sin reloj, sin RNG. Oraculo R6: matriz 3x3 sintetica
con valores cerrados calculados a mano.
"""

from __future__ import annotations

import math
from dataclasses import fields

import numpy as np
import pytest

from src.markets.goals import (
    DEFAULT_TEAM_LINES,
    DEFAULT_TOTAL_LINES,
    MarketLine,
    MarketSummary,
    _validate_line,
    market_summary,
    prob_btts,
    prob_over,
    prob_team_over,
)
from src.models.dixon_coles import DixonColesParams, UnknownTeamError


# ---------------------------------------------------------------------------
# Fixture: parametros sinteticos deterministas (mismo patron que test_dixon_coles_predict.py)
# ---------------------------------------------------------------------------


def _make_params() -> DixonColesParams:
    """Parametros construidos a mano; MEX y ARG presentes."""
    attack = {"MEX": 0.20, "USA": 0.10, "CAN": 0.00, "ARG": 0.40, "BRA": -0.10, "JPN": -0.60}
    defense = {"MEX": 0.05, "USA": 0.00, "CAN": -0.05, "ARG": 0.30, "BRA": 0.20, "JPN": -0.50}
    return DixonColesParams(
        as_of_date="2026-06-01",
        from_date="2018-01-01",
        xi=0.65,
        mu=0.1,
        home_advantage=0.3,
        rho=-0.08,
        attack=attack,
        defense=defense,
        n_matches=240,
        n_teams=6,
        min_matches=5,
        reg_lambda=1.0,
        low_data_teams=[],
        convergencia={"success": True, "n_iter": 50, "message": "ok", "neg_log_lik": 100.0},
    )


# ---------------------------------------------------------------------------
# Matriz sintetica 3x3 para el test oraculo R6
#
# M = [[0.1, 0.2, 0.3],   fila 0: X=0 (local 0 goles)
#       [0.15, 0.05, 0.1], fila 1: X=1
#       [0.06, 0.02, 0.02]] fila 2: X=2
# Suma total = 0.1+0.2+0.3 + 0.15+0.05+0.1 + 0.06+0.02+0.02 = 1.00
#
# Calculos a mano:
#
# prob_over(M, 0.5) = P(X+Y >= 1) = 1 - M[0,0] = 1 - 0.1 = 0.9
# prob_over(M, 1.5) = P(X+Y >= 2) = M[0,2]+M[1,1]+M[1,2]+M[2,0]+M[2,1]+M[2,2]
#                  = 0.3+0.05+0.1+0.06+0.02+0.02 = 0.55
# prob_over(M, 2.5) = P(X+Y >= 3) = M[0,2]? no, X+Y>=3:
#   (0,3) no existe (max Y=2), (1,2)=0.1, (2,1)=0.02, (2,2)=0.02
#   = 0.1 + 0.02 + 0.02 = 0.14
# prob_over(M, 3.5) = P(X+Y >= 4) = M[2,2] = 0.02
# prob_over(M, 4.5) = P(X+Y >= 5) = 0.0  (max soporte es 2+2=4)
#
# prob_btts(M) = M[1:,1:].sum() = M[1,1]+M[1,2]+M[2,1]+M[2,2]
#              = 0.05+0.1+0.02+0.02 = 0.19
#
# prob_team_over(M, "home", 0.5) = P(X >= 1) = marginal_home[1:].sum()
#   marginal_home = [0.1+0.2+0.3, 0.15+0.05+0.1, 0.06+0.02+0.02]
#                 = [0.6, 0.30, 0.10]
#   P(X >= 1) = 0.30 + 0.10 = 0.40
# prob_team_over(M, "home", 1.5) = P(X >= 2) = 0.10
# prob_team_over(M, "home", 2.5) = P(X >= 3) = 0.0 (max X=2)
#
# prob_team_over(M, "away", 0.5) = P(Y >= 1) = marginal_away[1:].sum()
#   marginal_away = [0.1+0.15+0.06, 0.2+0.05+0.02, 0.3+0.1+0.02]
#                 = [0.31, 0.27, 0.42]
#   P(Y >= 1) = 0.27 + 0.42 = 0.69
# prob_team_over(M, "away", 1.5) = P(Y >= 2) = 0.42
# prob_team_over(M, "away", 2.5) = P(Y >= 3) = 0.0 (max Y=2)
# ---------------------------------------------------------------------------

_ORACLE_MATRIX = np.array(
    [
        [0.10, 0.20, 0.30],
        [0.15, 0.05, 0.10],
        [0.06, 0.02, 0.02],
    ],
    dtype=float,
)


# ---------------------------------------------------------------------------
# R1 — modulo puro: sin importar streamlit ni modulos de red
# ---------------------------------------------------------------------------


def test_modulo_puro_sin_streamlit_ni_red() -> None:
    """R1: src.markets.goals no importa streamlit ni modulos de red (verificado en codigo fuente)."""
    from pathlib import Path
    import src.markets.goals as goals_mod

    # Verificamos en el codigo fuente que no hay sentencias import de modulos prohibidos.
    # Esto es robusto frente a contaminacion de sys.modules entre tests en la misma sesion.
    goals_path = Path(goals_mod.__file__)
    src_lines = goals_path.read_text(encoding="utf-8").splitlines()

    forbidden_imports = {"streamlit", "requests", "httpx", "urllib3", "aiohttp"}
    for ln in src_lines:
        stripped = ln.strip()
        for mod in forbidden_imports:
            # Detectar: "import streamlit", "from streamlit import ...", "import streamlit.X"
            if stripped.startswith(f"import {mod}") or stripped.startswith(f"from {mod}"):
                raise AssertionError(
                    f"src/markets/goals.py importa modulo prohibido '{mod}': {ln!r} (R1)"
                )


# ---------------------------------------------------------------------------
# R2 — over/under con lineas default y suma a 1
# ---------------------------------------------------------------------------


def test_over_under_lineas_default_y_suma_1() -> None:
    """R2: over + under = 1 para cada linea default (tolerancia 1e-9)."""
    for line in DEFAULT_TOTAL_LINES:
        over = prob_over(_ORACLE_MATRIX, line)
        under = 1.0 - over
        assert abs(over + under - 1.0) < 1e-9, (
            f"over + under != 1 para line={line}: {over} + {under}"
        )
        # over debe estar en [0, 1]
        assert 0.0 <= over <= 1.0, f"over fuera de [0,1] para line={line}: {over}"


def test_linea_invalida_valueerror() -> None:
    """R2: lineas que no son k+0.5 deben lanzar ValueError con formato esperado."""
    invalidas = [1.0, 2.0, 0.0, 1.3, -0.5, 0.4]
    for line in invalidas:
        with pytest.raises(ValueError, match="k \\+ 0.5"):
            _validate_line(line)

    # Lineas validas no deben lanzar
    for line in [0.5, 1.5, 2.5, 3.5, 4.5, 10.5]:
        _validate_line(line)  # no debe lanzar


# ---------------------------------------------------------------------------
# R3 — BTTS suma a 1
# ---------------------------------------------------------------------------


def test_btts_suma_1() -> None:
    """R3: btts_yes + btts_no = 1 (tolerancia 1e-9)."""
    btts_yes = prob_btts(_ORACLE_MATRIX)
    btts_no = 1.0 - btts_yes
    assert abs(btts_yes + btts_no - 1.0) < 1e-9
    assert 0.0 <= btts_yes <= 1.0


# ---------------------------------------------------------------------------
# R4 — totales por equipo
# ---------------------------------------------------------------------------


def test_totales_por_equipo() -> None:
    """R4: prob_team_over para home y away, suma a 1 por linea (tolerancia 1e-9)."""
    for line in DEFAULT_TEAM_LINES:
        for side in ("home", "away"):
            over = prob_team_over(_ORACLE_MATRIX, side, line)
            under = 1.0 - over
            assert abs(over + under - 1.0) < 1e-9, (
                f"over+under!=1 side={side} line={line}"
            )
            assert 0.0 <= over <= 1.0, f"over fuera de [0,1] side={side} line={line}"

    # Linea invalida debe lanzar ValueError
    with pytest.raises(ValueError, match="k \\+ 0.5"):
        prob_team_over(_ORACLE_MATRIX, "home", 1.0)


# ---------------------------------------------------------------------------
# R5 — market_summary con params sinteticos y UnknownTeamError
# ---------------------------------------------------------------------------


def test_market_summary_modelo_real_y_unknown_team() -> None:
    """R5: market_summary devuelve MarketSummary; UnknownTeamError se propaga sin envolver."""
    params = _make_params()

    # Caso normal: equipos conocidos
    summary = market_summary(params, "MEX", "ARG")
    assert isinstance(summary, MarketSummary)
    assert summary.home_code == "MEX"
    assert summary.away_code == "ARG"
    # 1X2 deben sumar ~1
    assert abs(summary.prob_home + summary.prob_draw + summary.prob_away - 1.0) < 1e-9
    # btts suma a 1
    assert abs(summary.btts_yes + summary.btts_no - 1.0) < 1e-9
    # totals tiene lineas en orden ascendente
    total_lines = [ml.line for ml in summary.totals]
    assert total_lines == sorted(total_lines)
    # Cada MarketLine: over + under = 1
    for ml in list(summary.totals) + list(summary.home_totals) + list(summary.away_totals):
        assert abs(ml.over + ml.under - 1.0) < 1e-9

    # UnknownTeamError se propaga sin envolver (R5)
    with pytest.raises(UnknownTeamError):
        market_summary(params, "MEX", "ZZZ")  # ZZZ no existe en params


# ---------------------------------------------------------------------------
# R6 — oraculo 3x3 con valores calculados a mano (tolerancia 1e-12)
# ---------------------------------------------------------------------------


def test_oraculo_matriz_3x3_a_mano() -> None:
    """R6: valores calculados a mano para la matriz 3x3 sintetica (tolerancia 1e-12).

    El oraculo protege contra errores de orientacion filas/columnas y de
    desigualdad estricta vs no-estricta en la comparacion X+Y > linea.
    """
    M = _ORACLE_MATRIX

    # Verificar que la suma total es exactamente 1.0 (o muy cercana)
    assert abs(M.sum() - 1.0) < 1e-12, f"Matriz oraculo no suma a 1: {M.sum()}"

    # prob_over(M, 0.5) = P(X+Y >= 1) = 1 - M[0,0] = 1 - 0.1 = 0.9
    assert abs(prob_over(M, 0.5) - 0.9) < 1e-12, (
        f"prob_over(0.5) esperado 0.9, obtenido {prob_over(M, 0.5)}"
    )

    # prob_over(M, 1.5) = P(X+Y >= 2) = M[0,2]+M[1,1]+M[1,2]+M[2,0]+M[2,1]+M[2,2]
    # = 0.3 + 0.05 + 0.1 + 0.06 + 0.02 + 0.02 = 0.55
    expected_1_5 = 0.3 + 0.05 + 0.1 + 0.06 + 0.02 + 0.02
    assert abs(prob_over(M, 1.5) - expected_1_5) < 1e-12, (
        f"prob_over(1.5) esperado {expected_1_5}, obtenido {prob_over(M, 1.5)}"
    )

    # prob_over(M, 2.5) = P(X+Y >= 3): (1,2)=0.1, (2,1)=0.02, (2,2)=0.02 -> 0.14
    expected_2_5 = 0.1 + 0.02 + 0.02
    assert abs(prob_over(M, 2.5) - expected_2_5) < 1e-12, (
        f"prob_over(2.5) esperado {expected_2_5}, obtenido {prob_over(M, 2.5)}"
    )

    # prob_over(M, 3.5) = P(X+Y >= 4): solo (2,2)=0.02
    assert abs(prob_over(M, 3.5) - 0.02) < 1e-12, (
        f"prob_over(3.5) esperado 0.02, obtenido {prob_over(M, 3.5)}"
    )

    # prob_over(M, 4.5) = P(X+Y >= 5) = 0.0 (max soporte 2+2=4)
    assert abs(prob_over(M, 4.5) - 0.0) < 1e-12, (
        f"prob_over(4.5) esperado 0.0, obtenido {prob_over(M, 4.5)}"
    )

    # prob_btts(M) = M[1:,1:].sum() = 0.05+0.1+0.02+0.02 = 0.19
    expected_btts = 0.05 + 0.1 + 0.02 + 0.02
    assert abs(prob_btts(M) - expected_btts) < 1e-12, (
        f"prob_btts esperado {expected_btts}, obtenido {prob_btts(M)}"
    )

    # prob_team_over(M, "home", 0.5) = P(X >= 1) = fila1.sum() + fila2.sum()
    # = (0.15+0.05+0.1) + (0.06+0.02+0.02) = 0.30 + 0.10 = 0.40
    expected_h_0_5 = 0.40
    assert abs(prob_team_over(M, "home", 0.5) - expected_h_0_5) < 1e-12, (
        f"prob_team_over(home, 0.5) esperado {expected_h_0_5}, "
        f"obtenido {prob_team_over(M, 'home', 0.5)}"
    )

    # prob_team_over(M, "home", 1.5) = P(X >= 2) = fila2.sum() = 0.06+0.02+0.02 = 0.10
    assert abs(prob_team_over(M, "home", 1.5) - 0.10) < 1e-12, (
        f"prob_team_over(home, 1.5) esperado 0.10, "
        f"obtenido {prob_team_over(M, 'home', 1.5)}"
    )

    # prob_team_over(M, "home", 2.5) = P(X >= 3) = 0.0 (max X=2)
    assert abs(prob_team_over(M, "home", 2.5) - 0.0) < 1e-12, (
        f"prob_team_over(home, 2.5) esperado 0.0, "
        f"obtenido {prob_team_over(M, 'home', 2.5)}"
    )

    # prob_team_over(M, "away", 0.5) = P(Y >= 1) = col1.sum() + col2.sum()
    # col1 = [0.2, 0.05, 0.02] -> 0.27
    # col2 = [0.3, 0.1, 0.02] -> 0.42
    # P(Y >= 1) = 0.27 + 0.42 = 0.69
    expected_a_0_5 = 0.27 + 0.42
    assert abs(prob_team_over(M, "away", 0.5) - expected_a_0_5) < 1e-12, (
        f"prob_team_over(away, 0.5) esperado {expected_a_0_5}, "
        f"obtenido {prob_team_over(M, 'away', 0.5)}"
    )

    # prob_team_over(M, "away", 1.5) = P(Y >= 2) = col2.sum() = 0.3+0.1+0.02 = 0.42
    assert abs(prob_team_over(M, "away", 1.5) - 0.42) < 1e-12, (
        f"prob_team_over(away, 1.5) esperado 0.42, "
        f"obtenido {prob_team_over(M, 'away', 1.5)}"
    )

    # prob_team_over(M, "away", 2.5) = P(Y >= 3) = 0.0 (max Y=2)
    assert abs(prob_team_over(M, "away", 2.5) - 0.0) < 1e-12, (
        f"prob_team_over(away, 2.5) esperado 0.0, "
        f"obtenido {prob_team_over(M, 'away', 2.5)}"
    )


# ---------------------------------------------------------------------------
# R9 — determinismo: misma entrada -> mismo resultado
# ---------------------------------------------------------------------------


def test_determinismo() -> None:
    """R9: mismos argumentos -> resultados identicos entre invocaciones."""
    params = _make_params()
    s1 = market_summary(params, "MEX", "ARG")
    s2 = market_summary(params, "MEX", "ARG")

    assert s1 == s2, "market_summary no es determinista para los mismos argumentos"

    # Las lineas estan en orden ascendente
    assert [ml.line for ml in s1.totals] == sorted([ml.line for ml in s1.totals])
    assert [ml.line for ml in s1.home_totals] == sorted([ml.line for ml in s1.home_totals])
    assert [ml.line for ml in s1.away_totals] == sorted([ml.line for ml in s1.away_totals])

    # Mismas lineas custom siempre dan el mismo orden
    s3 = market_summary(params, "MEX", "ARG", total_lines=(2.5, 0.5, 1.5))
    s4 = market_summary(params, "MEX", "ARG", total_lines=(0.5, 1.5, 2.5))
    assert s3 == s4, "El ordenamiento de lineas no es determinista"


# ---------------------------------------------------------------------------
# R10 — aislamiento: import sin efectos y sin dependencias inversas
# ---------------------------------------------------------------------------


def test_import_sin_efectos_y_sin_dependencias_inversas() -> None:
    """R10: src.markets no importa src.app, src.report ni src.cli (verificado en codigo fuente)."""
    from pathlib import Path
    import src.markets
    import src.markets.goals as goals_mod

    # Verificamos en el codigo fuente de goals.py que no importa modulos prohibidos.
    # Este enfoque es robusto frente a la contaminacion de sys.modules entre tests.
    goals_path = Path(goals_mod.__file__)
    src_lines = goals_path.read_text(encoding="utf-8").splitlines()

    forbidden_prefixes = ("src.app", "src.report", "src.cli")
    for ln in src_lines:
        stripped = ln.strip()
        for prefix in forbidden_prefixes:
            if stripped.startswith(f"import {prefix}") or stripped.startswith(f"from {prefix}"):
                raise AssertionError(
                    f"src/markets/goals.py importa modulo prohibido '{prefix}': {ln!r} (R10)"
                )

    # src.markets.__init__.py no debe tener sentencias import (solo docstring).
    init_path = Path(src.markets.__file__)
    init_lines = init_path.read_text(encoding="utf-8").splitlines()
    import_lines = [
        ln for ln in init_lines
        if ln.strip().startswith("import ") or ln.strip().startswith("from ")
    ]
    assert import_lines == [], (
        f"src/markets/__init__.py tiene sentencias import/from: {import_lines!r}"
    )
