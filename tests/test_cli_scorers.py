"""Feature 11 — factor_jugadores, R7: CLI subcomandos ingest-goalscorers y scorers.

Tests 100% offline y deterministas. Mapeo de tasks.md:
  R7 → test_scorers_exito_y_topk, test_ingest_goalscorers, test_subcomandos_exactos_intactos,
        test_exit_codes
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import src.cli as cli
from src.ingestion.goalscorers import (
    GoalscorersDownloadError,
    GoalscorersSchemaError,
)
from src.models.dixon_coles import (
    DCConfig,
    DixonColesParams,
    NotFittedError,
    UnknownTeamError,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOALSCORERS_SAMPLE = (FIXTURES / "goalscorers_sample.csv").read_text(encoding="utf-8")
AS_OF = "2023-01-01"

# Conjunto EXACTO de subcomandos (los 9 previos + los 2 nuevos de la feature 11 + f24 + f25)
EXPECTED_SUBCOMMANDS = frozenset({
    "ingest-public",
    "build-features",
    "train",
    "predict",
    "schedule",
    "markets",
    "backtest",
    "predict-log",
    "evaluate",
    "ingest-goalscorers",  # Feature 11
    "scorers",             # Feature 11
    "simulate",            # Feature 13
    "ingest-elo",          # Feature 14
    "ingest-wiki-stats",    # Feature 15
    "ingest-roster",        # Feature 21
    "ingest-fotmob-stats",  # Feature 23
    "corners",              # Feature 24
    "count-market",         # Feature 25
    "ingest-ko",            # Feature 27
    "build-ko-fixtures",    # Feature 27
    "ingest-lineups",       # Feature 28
    "build-lineup-strength",# Feature 28
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_params_doc(**overrides) -> dict:
    """JSON sintético con TODAS las claves del contrato de la feature 3."""
    doc = {
        "as_of_date": AS_OF,
        "from_date": "2018-01-01",
        "xi": 0.35,
        "mu": 0.1,
        "home_advantage": 0.3,
        "rho": -0.08,
        "attack": {
            "ARG": 0.40, "BRA": -0.10, "FRA": 0.30, "KSA": -0.50, "AUS": -0.40,
            "MEX": 0.20, "USA": 0.10,
        },
        "defense": {
            "ARG": 0.30, "BRA": 0.20, "FRA": 0.25, "KSA": -0.40, "AUS": -0.30,
            "MEX": 0.05, "USA": 0.00,
        },
        "n_matches": 240,
        "n_teams": 7,
        "min_matches": 5,
        "reg_lambda": 0.25,
        "low_data_teams": [],
        "convergencia": {"success": True, "n_iter": 50, "message": "ok", "neg_log_lik": 100.0},
    }
    doc.update(overrides)
    return doc


def write_params(tmp_path: Path, **overrides) -> Path:
    """Persiste el JSON sintético en tmp_path."""
    path = tmp_path / "dixon_coles_params.json"
    path.write_text(json.dumps(make_params_doc(**overrides)), encoding="utf-8")
    return path


def write_player_factor(tmp_path: Path, as_of: str = AS_OF) -> Path:
    """Gold player_factor.csv sintético para tests offline."""
    path = tmp_path / "player_factor.csv"
    path.write_text(
        "as_of_date,team_code,scorer,goals_weighted,share\n"
        f"{as_of},ARG,Lionel Messi,3.0000000000,0.6000000000\n"
        f"{as_of},ARG,Enzo Fernandez,2.0000000000,0.4000000000\n"
        f"{as_of},FRA,Kylian Mbappe,2.0000000000,0.6667000000\n"
        f"{as_of},FRA,Olivier Giroud,1.0000000000,0.3333000000\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# R7: test_subcomandos_exactos_intactos
# ---------------------------------------------------------------------------


def test_subcomandos_exactos_intactos():
    """R7: el conjunto EXACTO de subcomandos = los 9 previos + {ingest-goalscorers, scorers}."""
    parser = cli.build_parser()
    # Obtener los subcomandos registrados
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices is not None:
            subparsers_action = action
            break

    assert subparsers_action is not None, "No se encontró el action de subparsers"
    registered = frozenset(subparsers_action.choices.keys())
    assert registered == EXPECTED_SUBCOMMANDS, (
        f"Subcomandos registrados difieren del conjunto esperado.\n"
        f"  Esperados: {sorted(EXPECTED_SUBCOMMANDS)}\n"
        f"  Encontrados: {sorted(registered)}\n"
        f"  Sobrantes: {sorted(registered - EXPECTED_SUBCOMMANDS)}\n"
        f"  Faltantes: {sorted(EXPECTED_SUBCOMMANDS - registered)}"
    )


# ---------------------------------------------------------------------------
# R7: test_ingest_goalscorers
# ---------------------------------------------------------------------------


def test_ingest_goalscorers_exito(tmp_path, monkeypatch, capsys):
    """R7/R1: ingest-goalscorers en éxito → imprime ✅ + exit 0 (monkeypatched, cero red)."""
    bronze_dir = tmp_path / "bronze" / "goalscorers"
    bronze_dir.mkdir(parents=True)
    csv_path = bronze_dir / "goalscorers.csv"
    meta_path = bronze_dir / "goalscorers.meta.json"
    csv_path.write_text(GOALSCORERS_SAMPLE, encoding="utf-8")
    meta_path.write_text(
        json.dumps({
            "url": "https://example.test/goalscorers.csv",
            "fetched_at": "2026-06-17T10:00:00+00:00",
            "sha256": "abc123" * 8 + "abcd",
            "n_rows": 14,
            "header": list([
                "date", "home_team", "away_team", "team", "scorer",
                "minute", "own_goal", "penalty"
            ]),
        }),
        encoding="utf-8",
    )

    def fake_ingest(fetched_at, **kwargs):
        return csv_path, meta_path

    monkeypatch.setattr(cli, "ingest_goalscorers", fake_ingest)

    exit_code = cli.main(["ingest-goalscorers"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "✅" in out


def test_ingest_goalscorers_error_descarga(monkeypatch, capsys):
    """R7/R1: error de descarga → exit 1 con mensaje accionable."""
    def fail_ingest(fetched_at, **kwargs):
        raise GoalscorersDownloadError(503, "https://example.test/")

    monkeypatch.setattr(cli, "ingest_goalscorers", fail_ingest)

    exit_code = cli.main(["ingest-goalscorers"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_ingest_goalscorers_error_schema(monkeypatch, capsys):
    """R7/R1: encabezado inválido → exit 1 con mensaje accionable."""
    from src.ingestion.goalscorers import EXPECTED_HEADER

    def fail_ingest(fetched_at, **kwargs):
        raise GoalscorersSchemaError(EXPECTED_HEADER, ["wrong", "header"])

    monkeypatch.setattr(cli, "ingest_goalscorers", fail_ingest)

    exit_code = cli.main(["ingest-goalscorers"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error:" in err


# ---------------------------------------------------------------------------
# R7: test_scorers_exito_y_topk
# ---------------------------------------------------------------------------


def test_scorers_exito_y_topk(tmp_path, capsys):
    """R7: scorers con --home ARG --away FRA → exit 0 + tabla con prob_score."""
    params_path = write_params(tmp_path)
    player_factor_path = write_player_factor(tmp_path)

    exit_code = cli.main([
        "scorers",
        "--home", "ARG",
        "--away", "FRA",
        "--top-k", "3",
        "--params", str(params_path),
        "--player-factor", str(player_factor_path),
    ])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "✅" in out
    # Debe mostrar jugadores de ARG
    assert "Lionel Messi" in out or "Enzo Fernandez" in out
    # Debe mostrar jugadores de FRA
    assert "Kylian Mbappe" in out or "Olivier Giroud" in out
    # Debe mencionar lambda y probabilidad
    assert "P(marca)" in out or "%" in out


def test_scorers_as_of_inyectado(tmp_path, capsys):
    """R7/R8: --as-of se usa como fecha de corte, no el reloj del sistema."""
    params_path = write_params(tmp_path)
    player_factor_path = write_player_factor(tmp_path)

    exit_code = cli.main([
        "scorers",
        "--home", "ARG",
        "--away", "FRA",
        "--as-of", "2022-12-01",
        "--params", str(params_path),
        "--player-factor", str(player_factor_path),
    ])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "as_of=2022-12-01" in out


def test_scorers_sin_player_factor_construye_al_vuelo(tmp_path, monkeypatch, capsys):
    """R7: si player_factor.csv no existe pero hay bronze, construye al vuelo."""
    params_path = write_params(tmp_path)
    # No creamos player_factor.csv: la ruta no existe
    no_factor_path = tmp_path / "no_factor.csv"

    # Crear bronze de goleadores
    bronze_dir = tmp_path / "bronze" / "goalscorers"
    bronze_dir.mkdir(parents=True)
    csv_path = bronze_dir / "goalscorers.csv"
    csv_path.write_text(GOALSCORERS_SAMPLE, encoding="utf-8")

    # Patchear bronze_goalscorers_paths para que apunte al tmp_path
    monkeypatch.setattr(cli, "bronze_goalscorers_paths", lambda: (csv_path, csv_path.with_suffix(".meta.json")))

    exit_code = cli.main([
        "scorers",
        "--home", "ARG",
        "--away", "FRA",
        "--params", str(params_path),
        "--player-factor", str(no_factor_path),
    ])
    assert exit_code == 0


def test_scorers_sin_datos_jugadores_muestra_aviso(tmp_path, capsys):
    """R7: si no hay datos de goleadores para un equipo, muestra aviso sin romper."""
    params_path = write_params(tmp_path)
    # player_factor solo tiene ARG, no FRA
    player_factor_path = tmp_path / "player_factor_partial.csv"
    player_factor_path.write_text(
        f"as_of_date,team_code,scorer,goals_weighted,share\n"
        f"{AS_OF},ARG,Lionel Messi,3.0000000000,1.0000000000\n",
        encoding="utf-8",
    )

    exit_code = cli.main([
        "scorers",
        "--home", "ARG",
        "--away", "FRA",
        "--params", str(params_path),
        "--player-factor", str(player_factor_path),
    ])
    assert exit_code == 0
    out = capsys.readouterr().out
    # Debe indicar ausencia de datos históricos para FRA (mensaje exacto de cmd_scorers)
    assert "sin datos históricos" in out


def test_scorers_con_roster(tmp_path, capsys):
    """R7/R5: --roster aplica multiplicador de ataque correctamente."""
    params_path = write_params(tmp_path)
    player_factor_path = write_player_factor(tmp_path)

    # Roster CSV con jugadores de ARG disponibles
    roster_path = tmp_path / "roster.csv"
    roster_path.write_text(
        "team_code,scorer\nARG,Lionel Messi\n",
        encoding="utf-8",
    )

    exit_code = cli.main([
        "scorers",
        "--home", "ARG",
        "--away", "FRA",
        "--params", str(params_path),
        "--player-factor", str(player_factor_path),
        "--roster", str(roster_path),
    ])
    assert exit_code == 0
    out = capsys.readouterr().out
    # Con roster, debe mostrar el multiplicador
    assert "roster" in out.lower() or "×" in out


# ---------------------------------------------------------------------------
# R7: test_exit_codes
# ---------------------------------------------------------------------------


def test_exit_codes_codigo_invalido(tmp_path, capsys):
    """R7: código FIFA inválido → exit 1 con error accionable."""
    params_path = write_params(tmp_path)
    player_factor_path = write_player_factor(tmp_path)

    exit_code = cli.main([
        "scorers",
        "--home", "INVALID",
        "--away", "FRA",
        "--params", str(params_path),
        "--player-factor", str(player_factor_path),
    ])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_exit_codes_mismo_equipo(tmp_path, capsys):
    """R7: HOME == AWAY → exit 1 con mensaje accionable."""
    params_path = write_params(tmp_path)
    player_factor_path = write_player_factor(tmp_path)

    exit_code = cli.main([
        "scorers",
        "--home", "ARG",
        "--away", "ARG",
        "--params", str(params_path),
        "--player-factor", str(player_factor_path),
    ])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_exit_codes_sin_parametros_entrenados(tmp_path, capsys):
    """R7: sin parámetros entrenados → exit 1 con mensaje para ejecutar train."""
    player_factor_path = write_player_factor(tmp_path)
    no_params_path = tmp_path / "no_params.json"

    exit_code = cli.main([
        "scorers",
        "--home", "ARG",
        "--away", "FRA",
        "--params", str(no_params_path),
        "--player-factor", str(player_factor_path),
    ])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "train" in err.lower() or "parámetros" in err.lower()


def test_exit_codes_argparse_falta_home(capsys):
    """R7: argparse devuelve exit 2 cuando falta --home (argumento requerido)."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["scorers", "--away", "FRA"])
    assert exc_info.value.code == 2


def test_exit_codes_exito_es_cero(tmp_path, capsys):
    """R7: ejecución exitosa devuelve exactamente exit 0."""
    params_path = write_params(tmp_path)
    player_factor_path = write_player_factor(tmp_path)

    exit_code = cli.main([
        "scorers",
        "--home", "ARG",
        "--away", "FRA",
        "--params", str(params_path),
        "--player-factor", str(player_factor_path),
    ])
    assert exit_code == 0


# ---------------------------------------------------------------------------
# R7: build-features extiende player_factor sin romper flujo previo
# ---------------------------------------------------------------------------


def test_build_features_sin_bronze_goalscorers_no_rompe(tmp_path, monkeypatch, capsys):
    """R7: build-features sin bronze de goleadores → aviso en stderr, exit 0 (flujo intacto)."""
    # Monkeypatch build_all para devolver summary sintético sin tocar silver real
    def fake_build_all(as_of_date):
        return {
            "n_matches_silver": 100,
            "n_teams_gold": 48,
            "paths": {
                "matches": str(tmp_path / "silver" / "matches.csv"),
                "elo_history": str(tmp_path / "gold" / "elo_history.csv"),
                "team_features": str(tmp_path / "gold" / "team_features.csv"),
            },
        }

    monkeypatch.setattr(cli, "build_all", fake_build_all)

    # bronze_goalscorers_paths apunta a archivo inexistente (no hay bronze de goleadores)
    no_csv = tmp_path / "bronze" / "goalscorers" / "goalscorers.csv"
    monkeypatch.setattr(cli, "bronze_goalscorers_paths", lambda: (no_csv, no_csv.with_suffix(".meta.json")))

    exit_code = cli.main(["build-features", "--as-of-date", "2026-06-01"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "✅" in out  # el flujo base sigue imprimiendo éxito


def test_build_features_con_bronze_goalscorers_construye_player_factor(tmp_path, monkeypatch, capsys):
    """R7: build-features con bronze de goleadores → construye player_factor.csv."""
    # Monkeypatch build_all para devolver summary sintético
    def fake_build_all(as_of_date):
        return {
            "n_matches_silver": 100,
            "n_teams_gold": 48,
            "paths": {
                "matches": str(tmp_path / "silver" / "matches.csv"),
                "elo_history": str(tmp_path / "gold" / "elo_history.csv"),
                "team_features": str(tmp_path / "gold" / "team_features.csv"),
            },
        }

    monkeypatch.setattr(cli, "build_all", fake_build_all)

    # Crear bronze de goleadores
    bronze_dir = tmp_path / "bronze" / "goalscorers"
    bronze_dir.mkdir(parents=True)
    csv_path = bronze_dir / "goalscorers.csv"
    csv_path.write_text(GOALSCORERS_SAMPLE, encoding="utf-8")

    # Patchear bronze_goalscorers_paths y DEFAULT_PLAYER_FACTOR_PATH
    monkeypatch.setattr(
        cli, "bronze_goalscorers_paths",
        lambda: (csv_path, csv_path.with_suffix(".meta.json"))
    )

    gold_path = tmp_path / "data" / "gold" / "player_factor.csv"
    monkeypatch.setattr(cli, "DEFAULT_PLAYER_FACTOR_PATH", gold_path)

    # Patchear build_player_factor para que escriba en tmp_path
    from src.players import factor as factor_mod

    original_build = factor_mod.build_player_factor

    def patched_build(events, as_of_date, xi=DCConfig.xi, out_path=factor_mod.DEFAULT_GOLD_PATH):
        gold_path.parent.mkdir(parents=True, exist_ok=True)
        return original_build(events, as_of_date, xi=xi, out_path=gold_path)

    monkeypatch.setattr(factor_mod, "build_player_factor", patched_build)

    exit_code = cli.main(["build-features", "--as-of-date", AS_OF])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "✅" in out
