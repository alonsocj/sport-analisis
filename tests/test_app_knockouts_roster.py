"""tests/test_app_knockouts_roster.py — Tests de Feature 21: roster en el panel de knockouts (R3).

100% offline, sin red, sin Streamlit AppTest (demasiado pesado). Prueba las funciones
puras directamente: _load_rosters, _load_unavailable, _filter_and_renormalize y
_compute_analisis_data con y sin parámetros de roster.

Mapeo de trazabilidad:
- test_filtra_no_disponibles_y_renormaliza    → R3 (_filter_and_renormalize)
- test_sin_roster_igual_a_f20                → R3 (sin roster → comportamiento F20 intacto)
- test_nota_bajas_presente                   → R3 (unavail_map en resultado _compute_analisis_data)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.app.tabs.knockouts import (
    _filter_and_renormalize,
    _load_rosters,
    _load_unavailable,
    _compute_analisis_data,
)
from src.players.factor import PlayerRate

# ---------------------------------------------------------------------------
# Constantes y fixtures sintéticas (offline, sin red)
# ---------------------------------------------------------------------------

AS_OF = "2026-06-01"

_PARAMS_DICT: dict = {
    "as_of_date": AS_OF,
    "from_date": "2018-01-01",
    "xi": 0.35,
    "mu": 0.1,
    "home_advantage": 0.3,
    "rho": -0.05,
    "attack": {
        "ARG": 0.50,
        "BRA": 0.20,
        "FRA": 0.30,
        "MEX": 0.15,
        "USA": 0.10,
        "CAN": 0.05,
    },
    "defense": {
        "ARG": 0.40,
        "BRA": 0.25,
        "FRA": 0.15,
        "MEX": 0.05,
        "USA": 0.00,
        "CAN": -0.05,
    },
    "n_matches": 100,
    "n_teams": 6,
    "min_matches": 5,
    "reg_lambda": 0.25,
    "low_data_teams": [],
    "convergencia": {
        "success": True,
        "n_iter": 50,
        "message": "ok",
        "neg_log_lik": 90.0,
    },
}

_PLAYER_FACTOR_CONTENT = (
    f"as_of_date,team_code,scorer,goals_weighted,share\n"
    f"{AS_OF},ARG,Messi,5.0000000000,0.5000000000\n"
    f"{AS_OF},ARG,Di Maria,3.0000000000,0.3000000000\n"
    f"{AS_OF},ARG,Lautaro,2.0000000000,0.2000000000\n"
    f"{AS_OF},BRA,Vinicius,4.0000000000,0.5000000000\n"
    f"{AS_OF},BRA,Rodrygo,2.5000000000,0.3125000000\n"
    f"{AS_OF},BRA,Endrick,1.5000000000,0.1875000000\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_synthetic_params():
    """Carga DixonColesParams desde el dict sintético (sin disco permanente)."""
    from src.models.dixon_coles import load_params

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_PARAMS_DICT, fh)
        tmp = Path(fh.name)

    try:
        return load_params(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _make_player_factor(tmp_path: Path) -> Path:
    pf = tmp_path / "player_factor.csv"
    pf.write_text(_PLAYER_FACTOR_CONTENT, encoding="utf-8")
    return pf


def _make_rosters_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Crea un r32_rosters.csv sintético."""
    import csv

    path = tmp_path / "rosters.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["team_code", "scorer"])
        w.writeheader()
        w.writerows(rows)
    return path


def _make_unavailable_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Crea un r32_unavailable.csv sintético."""
    import csv

    path = tmp_path / "unavail.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["team_code", "player", "reason"])
        w.writeheader()
        w.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# R3: test_filtra_no_disponibles_y_renormaliza
# ---------------------------------------------------------------------------


def test_filtra_no_disponibles_y_renormaliza():
    """R3: _filter_and_renormalize filtra jugadores no disponibles y renormaliza shares."""
    rates = [
        PlayerRate(team_code="ARG", scorer="Messi", goals_weighted=5.0, share=0.5),
        PlayerRate(team_code="ARG", scorer="Di Maria", goals_weighted=3.0, share=0.3),
        PlayerRate(team_code="ARG", scorer="Lautaro", goals_weighted=2.0, share=0.2),
        PlayerRate(team_code="BRA", scorer="Vinicius", goals_weighted=4.0, share=0.5),
    ]

    # Solo Messi y Lautaro están disponibles
    available = ["Messi", "Lautaro"]
    result = _filter_and_renormalize(rates, "ARG", available)

    arg_result = [r for r in result if r.team_code == "ARG"]
    arg_scorers = {r.scorer for r in arg_result}

    # Di Maria debe estar excluido
    assert "Di Maria" not in arg_scorers
    assert "Messi" in arg_scorers
    assert "Lautaro" in arg_scorers

    # Verificar renormalización: shares deben sumar 1
    total_share = sum(r.share for r in arg_result)
    assert abs(total_share - 1.0) < 1e-9, f"Shares no suman 1: {total_share}"

    # Messi tenía share 0.5 y Lautaro 0.2; suma original = 0.7
    messi_rate = next(r for r in arg_result if r.scorer == "Messi")
    lautaro_rate = next(r for r in arg_result if r.scorer == "Lautaro")
    assert abs(messi_rate.share - 0.5 / 0.7) < 1e-9
    assert abs(lautaro_rate.share - 0.2 / 0.7) < 1e-9

    # Brasil debe permanecer intacto
    bra_result = [r for r in result if r.team_code == "BRA"]
    assert len(bra_result) == 1
    assert bra_result[0].scorer == "Vinicius"
    assert bra_result[0].share == 0.5  # sin cambios


def test_filter_available_vacio_no_filtra():
    """R3: lista available vacía → rates sin modificar (degradación elegante)."""
    rates = [
        PlayerRate(team_code="ARG", scorer="Messi", goals_weighted=5.0, share=0.5),
        PlayerRate(team_code="ARG", scorer="Di Maria", goals_weighted=3.0, share=0.5),
    ]
    result = _filter_and_renormalize(rates, "ARG", [])
    # Sin filtro → rates originales
    assert result is rates


def test_filter_sin_match_no_filtra():
    """R3: available sin ningún jugador en rates → rates sin modificar (best-effort)."""
    rates = [
        PlayerRate(team_code="ARG", scorer="Messi", goals_weighted=5.0, share=1.0),
    ]
    result = _filter_and_renormalize(rates, "ARG", ["Jugador Desconocido"])
    # Sin match → no filtrar
    assert result is rates


def test_filter_otros_equipos_intactos():
    """R3: _filter_and_renormalize no modifica rates de equipos ajenos."""
    rates = [
        PlayerRate(team_code="ARG", scorer="Messi", goals_weighted=5.0, share=0.6),
        PlayerRate(team_code="ARG", scorer="Di Maria", goals_weighted=3.0, share=0.4),
        PlayerRate(team_code="BRA", scorer="Vinicius", goals_weighted=4.0, share=1.0),
        PlayerRate(team_code="FRA", scorer="Mbappe", goals_weighted=5.0, share=1.0),
    ]
    available = ["Messi"]
    result = _filter_and_renormalize(rates, "ARG", available)

    bra = next(r for r in result if r.team_code == "BRA")
    fra = next(r for r in result if r.team_code == "FRA")
    assert bra.share == 1.0
    assert fra.share == 1.0


# ---------------------------------------------------------------------------
# R3: test_sin_roster_igual_a_f20
# ---------------------------------------------------------------------------


def test_sin_roster_igual_a_f20(tmp_path):
    """R3: sin roster (rosters_csv_str='') el cálculo es idéntico a Feature 20."""
    params = _make_synthetic_params()
    pf_path = _make_player_factor(tmp_path)

    # Sin roster
    result_no_roster = _compute_analisis_data(
        params,
        "ARG",
        "BRA",
        str(pf_path),
        top_k=3,
        rosters_csv_str="",
        unavailable_csv_str="",
    )

    # Verificar que el resultado es coherente con F20 (sin filtrado)
    assert result_no_roster["error"] is None
    assert result_no_roster["summary"] is not None
    assert result_no_roster["roster_map"] == {}
    assert result_no_roster["unavail_map"] == {}
    # Los scorers se calculan sin filtro
    scorers_home = result_no_roster["scorers_home"]
    assert scorers_home is not None
    # Todos los jugadores de ARG deben aparecer (sin filtro)
    scorer_names = {s.scorer for s in scorers_home}
    assert "Messi" in scorer_names


# ---------------------------------------------------------------------------
# R3: test_nota_bajas_presente
# ---------------------------------------------------------------------------


def test_nota_bajas_presente(tmp_path):
    """R3: con unavailable_csv → unavail_map en el resultado de _compute_analisis_data."""
    params = _make_synthetic_params()
    pf_path = _make_player_factor(tmp_path)

    # CSV de bajas para ARG
    unavail_csv = _make_unavailable_csv(
        tmp_path,
        [
            {"team_code": "ARG", "player": "Dybala", "reason": "Injured"},
            {"team_code": "ARG", "player": "Paredes", "reason": "Suspension"},
        ],
    )

    result = _compute_analisis_data(
        params,
        "ARG",
        "BRA",
        str(pf_path),
        top_k=3,
        rosters_csv_str="",
        unavailable_csv_str=str(unavail_csv),
    )

    assert result["error"] is None
    unavail_map = result["unavail_map"]
    assert "ARG" in unavail_map
    arg_bajas = unavail_map["ARG"]
    assert len(arg_bajas) == 2
    players = {b["player"] for b in arg_bajas}
    assert "Dybala" in players
    assert "Paredes" in players


def test_load_rosters_con_csv(tmp_path):
    """R3: _load_rosters carga correctamente el CSV de disponibles."""
    rosters_csv = _make_rosters_csv(
        tmp_path,
        [
            {"team_code": "ARG", "scorer": "Messi"},
            {"team_code": "ARG", "scorer": "Di Maria"},
            {"team_code": "BRA", "scorer": "Vinicius"},
        ],
    )

    roster = _load_rosters(rosters_csv)
    assert "ARG" in roster
    assert set(roster["ARG"]) == {"Messi", "Di Maria"}
    assert "BRA" in roster
    assert roster["BRA"] == ["Vinicius"]


def test_load_rosters_archivo_ausente():
    """R3: _load_rosters devuelve {} si el archivo no existe (degradación elegante)."""
    result = _load_rosters(Path("/no/existe/rosters.csv"))
    assert result == {}


def test_load_unavailable_con_csv(tmp_path):
    """R3: _load_unavailable carga correctamente el CSV de bajas."""
    unavail_csv = _make_unavailable_csv(
        tmp_path,
        [
            {"team_code": "ARG", "player": "Dybala", "reason": "Injured"},
        ],
    )

    unavail = _load_unavailable(unavail_csv)
    assert "ARG" in unavail
    assert len(unavail["ARG"]) == 1
    assert unavail["ARG"][0] == {"player": "Dybala", "reason": "Injured"}


def test_load_unavailable_archivo_ausente():
    """R3: _load_unavailable devuelve {} si el archivo no existe."""
    result = _load_unavailable(Path("/no/existe/unavail.csv"))
    assert result == {}


def test_compute_analisis_con_roster_filtra(tmp_path):
    """R3: con roster, _compute_analisis_data filtra jugadores no disponibles."""
    params = _make_synthetic_params()
    pf_path = _make_player_factor(tmp_path)

    # Solo Messi disponible para ARG
    rosters_csv = _make_rosters_csv(
        tmp_path,
        [
            {"team_code": "ARG", "scorer": "Messi"},
        ],
    )

    result = _compute_analisis_data(
        params,
        "ARG",
        "BRA",
        str(pf_path),
        top_k=5,
        rosters_csv_str=str(rosters_csv),
        unavailable_csv_str="",
    )

    assert result["error"] is None
    scorers_home = result["scorers_home"]
    assert scorers_home is not None
    # Solo Messi debe estar en los scorers de ARG
    scorer_names = {s.scorer for s in scorers_home}
    assert "Messi" in scorer_names
    assert "Di Maria" not in scorer_names
    assert "Lautaro" not in scorer_names

    # El roster_map debe estar cargado
    assert result["roster_map"].get("ARG") == ["Messi"]
