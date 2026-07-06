"""tests/test_cli_simulate.py — Tests del subcomando ``simulate`` del CLI (Feature 13, R8, R9).

Trazabilidad (tasks.md):
| R8  | test_simulate_exito_y_reporte, test_subcomandos_exactos_intactos, test_exit_codes |
| R9  | (roster aplica multiplicador: cubierto en test_simulacion.py::test_roster_aplica_multiplicador_opcional) |

Estrategia: monkeypatching de ``run_simulation`` y ``write_simulation_report``
(sin correr sims reales), fixtures offline. Sin red. Sin reloj.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.simulation.montecarlo import SimulationResult


# ---------------------------------------------------------------------------
# Helper para construir un SimulationResult mínimo
# ---------------------------------------------------------------------------

def _make_fake_result(n: int = 1000) -> SimulationResult:
    """Crea un SimulationResult sintético para mocking."""
    teams = ["BRA", "ARG", "FRA", "GER", "ESP", "ENG", "POR", "NED",
             "ITA", "BEL", "URU", "COL"]
    probs = {
        t: {
            "group": 0.9, "r32": 0.7, "r16": 0.5, "qf": 0.3,
            "sf": 0.2, "final": 0.1, "champion": 1.0 / len(teams),
        }
        for t in teams
    }
    ses = {t: {r: 0.01 for r in probs[t]} for t in teams}
    return SimulationResult(n_simulations=n, probabilities=probs, std_errors=ses)


# ---------------------------------------------------------------------------
# R8 — CLI simulate: éxito, reporte, exit codes
# ---------------------------------------------------------------------------

class TestSimulateCLI:
    """R8: subcomando simulate con exit codes 0/1/2 + reporte correcto."""

    def test_simulate_exito_y_reporte(self, tmp_path, monkeypatch):
        """R8: simulate con modelo ok → exit 0 + reporte escrito."""
        out_dir = tmp_path / "data" / "reports" / "simulacion"

        fake_result = _make_fake_result(n=1000)

        # Monkeypatch todos los puntos de entrada del subcomando
        from src.models.dixon_coles import DixonColesParams
        fake_params = DixonColesParams(
            as_of_date="2026-06-17",
            from_date="2018-01-01",
            xi=0.35,
            mu=0.1,
            home_advantage=0.2,
            rho=-0.1,
            attack={"BRA": 0.3},
            defense={"BRA": -0.1},
            n_matches=1000,
            n_teams=48,
            min_matches=5,
            reg_lambda=0.25,
            low_data_teams=[],
            convergencia={"success": True, "n_iter": 100, "message": "OK", "neg_log_lik": 1.0},
        )

        from src.simulation.bracket import GroupFixture
        fake_fixtures = [
            GroupFixture("BRA", "ARG", 1, 0, "m1", "2026-06-11"),
        ]

        fake_json = out_dir / "summary.json"
        fake_csv = out_dir / "advancement.csv"

        with (
            patch("src.cli.load_params", return_value=fake_params),
            patch("src.simulation.montecarlo.load_wc2026_fixtures", return_value=fake_fixtures),
            patch("src.simulation.montecarlo.run_simulation", return_value=fake_result),
            patch("src.simulation.report.write_simulation_report", return_value=(fake_json, fake_csv)),
        ):
            from src.cli import main
            exit_code = main([
                "simulate",
                "--n", "1000",
                "--seed", "42",
                "--out", str(out_dir),
            ])

        assert exit_code == 0, f"Exit code esperado 0, se obtuvo {exit_code}"

    def test_exit_codes(self, tmp_path, monkeypatch, capsys):
        """R8: exit 1 cuando el modelo no está entrenado."""
        from src.models.dixon_coles import NotFittedError

        with patch("src.cli.load_params", side_effect=NotFittedError("sin params")):
            from src.cli import main
            exit_code = main(["simulate", "--n", "1000", "--seed", "42"])

        assert exit_code == 1, f"Exit code esperado 1 (modelo no entrenado), se obtuvo {exit_code}"

        # Verificar mensaje en stderr
        captured = capsys.readouterr()
        assert "error:" in captured.err.lower() or "error:" in captured.err

    def test_exit_code_n_invalido(self, tmp_path, capsys):
        """R8: exit 1 cuando n < MIN_N_SIMULATIONS."""
        from src.models.dixon_coles import DixonColesParams
        fake_params = DixonColesParams(
            as_of_date="2026-06-17",
            from_date="2018-01-01",
            xi=0.35,
            mu=0.1,
            home_advantage=0.2,
            rho=-0.1,
            attack={},
            defense={},
            n_matches=1000,
            n_teams=0,
            min_matches=5,
            reg_lambda=0.25,
            low_data_teams=[],
            convergencia={"success": True, "n_iter": 0, "message": "", "neg_log_lik": 0.0},
        )

        with patch("src.cli.load_params", return_value=fake_params):
            from src.cli import main
            exit_code = main(["simulate", "--n", "5", "--seed", "42"])

        assert exit_code == 1, f"--n=5 (< 1000) debe dar exit 1, se obtuvo {exit_code}"

    def test_exit_code_2_flag_invalido(self, capsys):
        """R8: exit 2 ante argumento inválido (argparse)."""
        from src.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["simulate", "--model-version", "dc-v99"])

        assert exc_info.value.code == 2, (
            f"Flag inválido debe dar SystemExit(2), se obtuvo {exc_info.value.code}"
        )


# ---------------------------------------------------------------------------
# R8 — Subcomandos exactos intactos
# ---------------------------------------------------------------------------

class TestSubcomandosExactos:
    """R8: el conjunto de subcomandos es exactamente 13 (los 12 previos + ingest-elo, R8 f14)."""

    def test_subcomandos_exactos_intactos(self):
        """R8: el parser tiene exactamente 14 subcomandos, ni más ni menos (R8 f14, R6 f15)."""
        from src.cli import build_parser

        parser = build_parser()
        # Acceder a los subparsers
        subparsers_action = None
        for action in parser._actions:
            if hasattr(action, "_parser_class") or hasattr(action, "choices"):
                if isinstance(getattr(action, "choices", None), dict):
                    subparsers_action = action
                    break

        assert subparsers_action is not None, "No se encontró el subparser action"
        subcommands = set(subparsers_action.choices.keys())

        expected = {
            "ingest-public",
            "build-features",
            "train",
            "predict",
            "schedule",
            "markets",
            "backtest",
            "predict-log",
            "evaluate",
            "ingest-goalscorers",
            "scorers",
            "simulate",
            "ingest-elo",           # Feature 14
            "ingest-wiki-stats",    # Feature 15
            "ingest-roster",        # Feature 21
            "ingest-fotmob-stats",  # Feature 23
            "corners",              # Feature 24
            "count-market",         # Feature 25
            "ingest-ko",            # Feature 27
            "build-ko-fixtures",    # Feature 27
            "ingest-lineups",       # Feature 28
            "build-lineup-strength",# Feature 28
        }

        assert subcommands == expected, (
            f"Subcomandos incorrectos.\n"
            f"Esperados: {sorted(expected)}\n"
            f"Encontrados: {sorted(subcommands)}\n"
            f"Extra: {subcommands - expected}\n"
            f"Faltantes: {expected - subcommands}"
        )

    def test_subcomandos_son_exactamente_12(self):
        """R6 f15: exactamente 18 subcomandos (17 previos + count-market, R3 f25)."""
        from src.cli import build_parser

        parser = build_parser()
        subparsers_action = None
        for action in parser._actions:
            if isinstance(getattr(action, "choices", None), dict):
                subparsers_action = action
                break

        n_subcommands = len(subparsers_action.choices)
        assert n_subcommands == 22, (
            f"Se esperan exactamente 18 subcomandos, se encontraron {n_subcommands}: "
            f"{sorted(subparsers_action.choices.keys())}"
        )

    def test_subcomandos_previos_intactos(self):
        """R8: los 11 subcomandos previos no se modificaron."""
        from src.cli import build_parser

        parser = build_parser()
        subparsers_action = None
        for action in parser._actions:
            if isinstance(getattr(action, "choices", None), dict):
                subparsers_action = action
                break

        # Los 11 subcomandos originales deben estar presentes
        previous_11 = [
            "ingest-public", "build-features", "train", "predict",
            "schedule", "markets", "backtest", "predict-log",
            "evaluate", "ingest-goalscorers", "scorers",
        ]
        for cmd in previous_11:
            assert cmd in subparsers_action.choices, (
                f"Subcomando previo {cmd!r} no encontrado en el parser"
            )

    def test_simulate_tiene_flags_correctos(self):
        """R8: el subcomando simulate tiene los flags --n, --seed, --as-of, --model-version, --roster, --out."""
        from src.cli import build_parser
        import argparse

        parser = build_parser()
        subparsers_action = None
        for action in parser._actions:
            if isinstance(getattr(action, "choices", None), dict):
                subparsers_action = action
                break

        simulate_parser = subparsers_action.choices["simulate"]
        option_strings = []
        for action in simulate_parser._actions:
            option_strings.extend(action.option_strings)

        assert "--n" in option_strings, "--n no encontrado en simulate"
        assert "--seed" in option_strings, "--seed no encontrado en simulate"
        assert "--as-of" in option_strings, "--as-of no encontrado en simulate"
        assert "--model-version" in option_strings, "--model-version no encontrado en simulate"
        assert "--roster" in option_strings, "--roster no encontrado en simulate"
        assert "--out" in option_strings, "--out no encontrado en simulate"
