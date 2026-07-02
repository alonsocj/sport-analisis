"""tests/test_roster_normalize.py — Tests de normalización de rosters (Feature 21, R2).

Todos offline, sin red, funciones puras. Sin Streamlit ni fixtures de disco.

Mapeo de trazabilidad:
- test_mapeo_fifa_y_disponibles_vs_no    → R2 (lineup → filas CSV mapeadas correctamente)
- test_roster_csv_schema_compatible      → R2 (CSV tiene exactamente team_code,scorer)
- test_equipo_sin_mapeo_descartado       → R2 (equipo sin código FIFA → descartado, no aborta)
"""

from __future__ import annotations

import csv
import warnings
from pathlib import Path

import pytest

from src.ingestion.roster import (
    MatchRef,
    RawLineup,
    RosterCoverage,
    TeamLineup,
    normalize_rosters,
)

# ---------------------------------------------------------------------------
# Helpers de construcción de fixtures
# ---------------------------------------------------------------------------


def _make_match_ref(match_id: str = "001") -> MatchRef:
    return MatchRef(
        match_id=match_id,
        page_url=f"/matches/test-match/{match_id}",
        home_team="Argentina",
        away_team="Canada",
    )


def _make_lineup_arg(name: str, starters: list[str], subs: list[str], unavailable: list[dict] | None = None) -> TeamLineup:
    return TeamLineup(
        name=name,
        starters=starters,
        subs=subs,
        unavailable=unavailable or [],
    )


# ---------------------------------------------------------------------------
# R2: test_mapeo_fifa_y_disponibles_vs_no
# ---------------------------------------------------------------------------


def test_mapeo_fifa_y_disponibles_vs_no(tmp_path):
    """R2: lineup con equipos FIFA → filas disponibles e indisponibles correctas."""
    # Argentina tiene jugadores disponibles y una baja
    arg_lineup = _make_lineup_arg(
        name="Argentina",
        starters=["Messi", "Di Maria"],
        subs=["Lautaro"],
        unavailable=[{"name": "Dybala", "reason": "Injured"}],
    )
    # Canada tiene lineup limpio
    can_lineup = _make_lineup_arg(
        name="Canada",
        starters=["Alphonso Davies"],
        subs=["Jonathan David"],
    )

    raw = RawLineup(
        match_ref=_make_match_ref(),
        home=arg_lineup,
        away=can_lineup,
        has_lineup=True,
    )

    rosters_csv = tmp_path / "rosters.csv"
    unavail_csv = tmp_path / "unavail.csv"

    available_rows, unavailable_rows, coverage = normalize_rosters(
        [raw],
        rosters_csv=rosters_csv,
        unavailable_csv=unavail_csv,
    )

    # Verificar filas disponibles
    arg_scorers = [r["scorer"] for r in available_rows if r["team_code"] == "ARG"]
    can_scorers = [r["scorer"] for r in available_rows if r["team_code"] == "CAN"]

    assert set(arg_scorers) == {"Messi", "Di Maria", "Lautaro"}
    assert set(can_scorers) == {"Alphonso Davies", "Jonathan David"}

    # Verificar bajas
    arg_unavail = [r for r in unavailable_rows if r["team_code"] == "ARG"]
    assert len(arg_unavail) == 1
    assert arg_unavail[0]["player"] == "Dybala"
    assert arg_unavail[0]["reason"] == "Injured"

    # Coverage
    assert coverage.n_matches == 1
    assert coverage.n_with_lineup == 1
    assert coverage.n_teams_mapped == 2
    assert coverage.n_teams_discarded == 0


# ---------------------------------------------------------------------------
# R2: test_roster_csv_schema_compatible
# ---------------------------------------------------------------------------


def test_roster_csv_schema_compatible(tmp_path):
    """R2: r32_rosters.csv tiene exactamente columnas team_code,scorer."""
    arg_lineup = _make_lineup_arg(
        name="Argentina",
        starters=["Messi"],
        subs=[],
    )
    raw = RawLineup(
        match_ref=_make_match_ref(),
        home=arg_lineup,
        away=None,
        has_lineup=True,
    )

    rosters_csv = tmp_path / "rosters.csv"
    unavail_csv = tmp_path / "unavail.csv"

    normalize_rosters([raw], rosters_csv=rosters_csv, unavailable_csv=unavail_csv)

    assert rosters_csv.is_file()
    with rosters_csv.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])

    assert fieldnames == ["team_code", "scorer"], (
        f"Esquema incorrecto: {fieldnames!r}, se esperaba ['team_code', 'scorer']"
    )


def test_unavailable_csv_schema(tmp_path):
    """R2: r32_unavailable.csv tiene exactamente columnas team_code,player,reason."""
    arg_lineup = _make_lineup_arg(
        name="Argentina",
        starters=[],
        subs=[],
        unavailable=[{"name": "Dybala", "reason": "Suspension"}],
    )
    raw = RawLineup(
        match_ref=_make_match_ref(),
        home=arg_lineup,
        away=None,
        has_lineup=True,
    )

    rosters_csv = tmp_path / "rosters.csv"
    unavail_csv = tmp_path / "unavail.csv"

    normalize_rosters([raw], rosters_csv=rosters_csv, unavailable_csv=unavail_csv)

    assert unavail_csv.is_file()
    with unavail_csv.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])

    assert fieldnames == ["team_code", "player", "reason"], (
        f"Esquema incorrecto: {fieldnames!r}"
    )


# ---------------------------------------------------------------------------
# R2: test_equipo_sin_mapeo_descartado
# ---------------------------------------------------------------------------


def test_equipo_sin_mapeo_descartado(tmp_path):
    """R2: equipo sin código FIFA → descartado con warn, no aborta el proceso."""
    # "Atlantis FC" no tiene mapeo FIFA
    unknown_lineup = _make_lineup_arg(
        name="Atlantis FC",
        starters=["Player A"],
        subs=[],
    )
    can_lineup = _make_lineup_arg(
        name="Canada",
        starters=["Alphonso Davies"],
        subs=[],
    )
    raw = RawLineup(
        match_ref=_make_match_ref(),
        home=unknown_lineup,
        away=can_lineup,
        has_lineup=True,
    )

    rosters_csv = tmp_path / "rosters.csv"
    unavail_csv = tmp_path / "unavail.csv"

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        available_rows, _, coverage = normalize_rosters(
            [raw], rosters_csv=rosters_csv, unavailable_csv=unavail_csv
        )

    # El equipo desconocido fue descartado con warn
    assert any("Atlantis FC" in str(warning.message) for warning in w), (
        "Se esperaba un UserWarning sobre 'Atlantis FC'"
    )
    assert coverage.n_teams_discarded == 1
    assert coverage.n_teams_mapped == 1

    # Solo Canada aparece en el CSV de disponibles
    team_codes = {r["team_code"] for r in available_rows}
    assert "CAN" in team_codes
    assert "Atlantis FC" not in team_codes


def test_normalize_lista_vacia(tmp_path):
    """R2: lista vacía → CSVs vacíos (solo header), coverage zeros."""
    rosters_csv = tmp_path / "rosters.csv"
    unavail_csv = tmp_path / "unavail.csv"

    available_rows, unavailable_rows, coverage = normalize_rosters(
        [], rosters_csv=rosters_csv, unavailable_csv=unavail_csv
    )

    assert available_rows == []
    assert unavailable_rows == []
    assert coverage.n_matches == 0
    assert coverage.n_with_lineup == 0
    assert coverage.n_teams_mapped == 0
    assert coverage.n_teams_discarded == 0
    assert rosters_csv.is_file()
    assert unavail_csv.is_file()


def test_equipo_sin_lineup_no_genera_filas(tmp_path):
    """R2: RawLineup sin home/away → no genera filas en CSVs."""
    raw = RawLineup(
        match_ref=_make_match_ref(),
        home=None,
        away=None,
        has_lineup=False,
    )

    rosters_csv = tmp_path / "rosters.csv"
    unavail_csv = tmp_path / "unavail.csv"

    available_rows, unavailable_rows, coverage = normalize_rosters(
        [raw], rosters_csv=rosters_csv, unavailable_csv=unavail_csv
    )

    assert available_rows == []
    assert unavailable_rows == []
    assert coverage.n_matches == 1
    assert coverage.n_with_lineup == 0
    assert coverage.n_teams_mapped == 0
