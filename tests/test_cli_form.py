"""tests/test_cli_form.py — Feature 16: forma_reciente, R6.

Trazabilidad (tasks.md):
| R6 | test_form_weight_en_predict, test_subcomandos_exactos_intactos,
|    | test_exit_codes_y_json                                               |

Principios:
- γ=0 (default) → comportamiento v1 EXACTAMENTE (no-regresión).
- γ>0 → form_factor aplicado; pero si silver no existe, cae gracefulmente.
- Los 14 subcomandos permanecen exactamente los mismos (no hay uno nuevo).
- El flag --form-weight existe en predict, backtest y simulate.
- 100% offline — sin red; form_factor mocked en los paths que requieren datos.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import src.cli as cli


# ---------------------------------------------------------------------------
# Fixtures compartidos (inline, sin fixture-fixture dependency)
# ---------------------------------------------------------------------------

AS_OF = "2026-06-01"

_PARAMS_DOC = {
    "as_of_date": AS_OF,
    "from_date": "2018-01-01",
    "xi": 0.65,
    "mu": 0.1,
    "home_advantage": 0.3,
    "rho": -0.08,
    "attack": {"ARG": 0.40, "BRA": -0.10, "MEX": 0.20, "USA": 0.10},
    "defense": {"ARG": 0.30, "BRA": 0.20, "MEX": 0.05, "USA": 0.00},
    "n_matches": 240,
    "n_teams": 4,
    "min_matches": 5,
    "reg_lambda": 1.0,
    "low_data_teams": [],
    "convergencia": {"success": True, "n_iter": 50, "message": "ok", "neg_log_lik": 100.0},
}


def _write_params(tmp_path: Path, **overrides) -> Path:
    doc = {**_PARAMS_DOC, **overrides}
    p = tmp_path / "params.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _no_gold(tmp_path: Path) -> str:
    return str(tmp_path / "no_gold" / "team_features.csv")


# ---------------------------------------------------------------------------
# R6 — flag --form-weight en predict, backtest, simulate
# ---------------------------------------------------------------------------

class TestFormWeightFlagR6:
    """R6: --form-weight registrado en predict, backtest y simulate; no en otros."""

    def test_predict_acepta_form_weight_cero(self, tmp_path, capsys):
        """R6: --form-weight 0.0 en predict → γ=0 → salida idéntica a v1 (no-regresión)."""
        params_path = _write_params(tmp_path)
        rc = cli.main([
            "predict", "ARG", "MEX",
            "--params", str(params_path),
            "--features", _no_gold(tmp_path),
            "--form-weight", "0.0",
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Argentina (ARG)" in out or "ARG" in out
        # NO debe mencionar forma reciente activa
        assert "Forma reciente activa" not in out

    def test_predict_form_weight_en_json(self, tmp_path, capsys):
        """R6: --json incluye clave form_weight en el documento (R6 + JSON contract)."""
        params_path = _write_params(tmp_path)
        rc = cli.main([
            "predict", "ARG", "MEX",
            "--params", str(params_path),
            "--features", _no_gold(tmp_path),
            "--form-weight", "0.0",
            "--json",
        ])
        assert rc == 0
        doc = json.loads(capsys.readouterr().out)
        assert "form_weight" in doc
        assert doc["form_weight"] == 0.0

    def test_predict_form_weight_positivo_no_aborta_sin_silver(self, tmp_path, capsys):
        """R6/R7: γ>0 sin silver en disco → advertencia suave, predicción v1, exit 0."""
        params_path = _write_params(tmp_path)
        # No creamos data/silver/matches.csv → _build_form_factor devuelve None
        rc = cli.main([
            "predict", "ARG", "MEX",
            "--params", str(params_path),
            "--features", _no_gold(tmp_path),
            "--form-weight", "0.3",
        ])
        # Sin datos, no aborta (degradación graceful)
        assert rc == 0, "γ>0 sin silver debe terminar con exit 0 (degradación suave)"

    def test_predict_form_weight_con_form_factor_mocked(self, tmp_path, capsys, monkeypatch):
        """R6: con γ=0.3 y form_factor mocked → lambda_home *= mult_home (R4 DC integration)."""
        import math as _math
        params_path = _write_params(tmp_path)

        # Mock _build_form_factor para retornar un callable con multiplicadores conocidos
        MULT_HOME = 1.2
        MULT_AWAY = 0.9

        monkeypatch.setattr(
            cli, "_build_form_factor",
            lambda gamma, as_of, use_xg=False: (lambda h, a: (MULT_HOME, MULT_AWAY)) if gamma > 0 else None,
        )

        rc = cli.main([
            "predict", "ARG", "MEX",
            "--params", str(params_path),
            "--features", _no_gold(tmp_path),
            "--form-weight", "0.3",
        ])
        out = capsys.readouterr().out
        assert rc == 0

        # lambda_home base: exp(0.1 + 0.40 - 0.05) * MULT_HOME
        # defense de MEX=0.05, attack de ARG=0.40, mu=0.1, home_advantage=0
        lambda_home_v1 = _math.exp(0.1 + 0.40 - 0.05)
        lambda_home_v2 = lambda_home_v1 * MULT_HOME
        assert f"{lambda_home_v2:.2f}" in out, (
            f"Lambda home ajustada por forma ({lambda_home_v2:.2f}) no encontrada en salida"
        )
        # Debe indicar forma activa
        assert "Forma reciente activa" in out

    def test_predict_form_weight_en_help(self):
        """R6: --form-weight documentado en el help de predict."""
        import argparse
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        predict_parser = sub.choices["predict"]
        help_text = predict_parser.format_help()
        assert "form-weight" in help_text or "form_weight" in help_text

    def test_backtest_form_weight_en_help(self):
        """R6: --form-weight documentado en el help de backtest."""
        import argparse
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        backtest_parser = sub.choices["backtest"]
        help_text = backtest_parser.format_help()
        assert "form-weight" in help_text or "form_weight" in help_text

    def test_simulate_form_weight_en_help(self):
        """R6: --form-weight documentado en el help de simulate."""
        import argparse
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        simulate_parser = sub.choices["simulate"]
        help_text = simulate_parser.format_help()
        assert "form-weight" in help_text or "form_weight" in help_text

    def test_form_weight_default_es_cero(self):
        """R6: --form-weight default=0.0 → no-regresión garantizada sin argumento."""
        parser = cli.build_parser()
        args = parser.parse_args(["predict", "ARG", "MEX"])
        assert hasattr(args, "form_weight")
        assert args.form_weight == 0.0

    def test_form_weight_default_backtest(self):
        """R6: --form-weight default=0.0 en backtest."""
        parser = cli.build_parser()
        args = parser.parse_args(["backtest"])
        assert hasattr(args, "form_weight")
        assert args.form_weight == 0.0

    def test_form_weight_default_simulate(self):
        """R6: --form-weight default=0.0 en simulate."""
        parser = cli.build_parser()
        args = parser.parse_args(["simulate"])
        assert hasattr(args, "form_weight")
        assert args.form_weight == 0.0

    def test_form_weight_argparse_type_float(self):
        """R6: --form-weight acepta float (no falla con 0.35 o 1.0)."""
        parser = cli.build_parser()
        args = parser.parse_args(["predict", "ARG", "BRA", "--form-weight", "0.35"])
        assert abs(args.form_weight - 0.35) < 1e-9


# ---------------------------------------------------------------------------
# R6 — subcomandos exactos intactos (14, no cambia el set)
# ---------------------------------------------------------------------------

class TestSubcomandosIntactosR6:
    """R6: feature 16 NO añade nuevos subcomandos — sigue siendo exactamente 14."""

    def test_14_subcomandos_exactos_intactos(self):
        """R6: exactamente 17 subcomandos (16 de f23 + corners de f24)."""
        import argparse
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        assert set(sub.choices) == {
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
            "ingest-elo",
            "ingest-wiki-stats",
            "ingest-roster",        # Feature 21
            "ingest-fotmob-stats",  # Feature 23
            "corners",              # Feature 24
            "count-market",         # Feature 25
            "ingest-ko",            # Feature 27
            "build-ko-fixtures",    # Feature 27
            "ingest-lineups",       # Feature 28
            "build-lineup-strength",# Feature 28
            "simulate-match",       # Feature 34
        }, "Feature 16 NO debe añadir subcomandos nuevos — solo flags a los existentes"
        assert len(sub.choices) == 23, f"Esperados 23, encontrados {len(sub.choices)}"

    def test_subcomandos_sin_form_weight_sin_atributo_por_defecto(self):
        """R6: subcomandos que NO son predict/backtest/simulate no tienen form_weight."""
        parser = cli.build_parser()
        # schedule y evaluate tienen argumentos opcionales → parse_args funciona
        for sub_name in ("schedule", "evaluate"):
            args = parser.parse_args([sub_name])
            # Estos subcomandos NO deben tener form_weight en su namespace
            assert not hasattr(args, "form_weight"), (
                f"{sub_name} NO debe exponer form_weight (Feature 16 solo aplica a "
                "predict/backtest/simulate)"
            )


# ---------------------------------------------------------------------------
# R6 — exit codes correctos con y sin --form-weight
# ---------------------------------------------------------------------------

class TestExitCodesR6:
    """R6: exit codes correctos con y sin --form-weight en predict."""

    def test_predict_form_weight_0_exit_0(self, tmp_path, capsys):
        """R6: predict con --form-weight 0.0 → exit 0."""
        params_path = _write_params(tmp_path)
        rc = cli.main([
            "predict", "ARG", "MEX",
            "--params", str(params_path),
            "--features", _no_gold(tmp_path),
            "--form-weight", "0.0",
        ])
        assert rc == 0

    def test_predict_json_con_form_weight_cero_parseable(self, tmp_path, capsys):
        """R6: --json --form-weight 0.0 → documento JSON válido con form_weight=0.0."""
        params_path = _write_params(tmp_path)
        rc = cli.main([
            "predict", "ARG", "MEX",
            "--params", str(params_path),
            "--features", _no_gold(tmp_path),
            "--json",
            "--form-weight", "0.0",
        ])
        assert rc == 0
        raw = capsys.readouterr().out
        doc = json.loads(raw)  # debe ser parseable
        assert doc["form_weight"] == 0.0
        assert "probs" in doc
        # Con γ=0 las probabilidades son las mismas que v1
        assert 0 < doc["probs"]["home"] < 1
        assert 0 < doc["probs"]["draw"] < 1
        assert 0 < doc["probs"]["away"] < 1

    def test_predict_json_probs_suman_1_con_form_weight_0(self, tmp_path, capsys):
        """R6/R4: γ=0 → probs idénticas a v1 → home+draw+away ≈ 1.0."""
        params_path = _write_params(tmp_path)
        rc = cli.main([
            "predict", "ARG", "MEX",
            "--params", str(params_path),
            "--features", _no_gold(tmp_path),
            "--json",
            "--form-weight", "0.0",
        ])
        assert rc == 0
        doc = json.loads(capsys.readouterr().out)
        total = doc["probs"]["home"] + doc["probs"]["draw"] + doc["probs"]["away"]
        assert abs(total - 1.0) < 1e-6, f"Probs no suman 1: {total}"

    def test_predict_json_forma_mocked_multiplica_lambdas(self, tmp_path, capsys, monkeypatch):
        """R6/R4: con form_factor mocked (mult=1.5,0.8) las λ' se reflejan en JSON."""
        import math as _m
        params_path = _write_params(tmp_path)

        MULT_HOME = 1.5
        MULT_AWAY = 0.8
        monkeypatch.setattr(
            cli, "_build_form_factor",
            lambda gamma, as_of, use_xg=False: (lambda h, a: (MULT_HOME, MULT_AWAY)) if gamma > 0 else None,
        )

        # Obtener λ v1 sin forma
        rc0 = cli.main([
            "predict", "ARG", "MEX",
            "--params", str(params_path),
            "--features", _no_gold(tmp_path),
            "--json",
            "--form-weight", "0.0",
        ])
        v1_doc = json.loads(capsys.readouterr().out)

        # Obtener λ v2 con forma
        rc2 = cli.main([
            "predict", "ARG", "MEX",
            "--params", str(params_path),
            "--features", _no_gold(tmp_path),
            "--json",
            "--form-weight", "0.3",
        ])
        v2_doc = json.loads(capsys.readouterr().out)

        assert rc0 == 0 and rc2 == 0

        lh_v1 = v1_doc["lambda_home"]
        la_v1 = v1_doc["lambda_away"]
        lh_v2 = v2_doc["lambda_home"]
        la_v2 = v2_doc["lambda_away"]

        assert abs(lh_v2 - lh_v1 * MULT_HOME) < 1e-6, (
            f"lambda_home esperado {lh_v1 * MULT_HOME:.6f}, obtenido {lh_v2:.6f}"
        )
        assert abs(la_v2 - la_v1 * MULT_AWAY) < 1e-6, (
            f"lambda_away esperado {la_v1 * MULT_AWAY:.6f}, obtenido {la_v2:.6f}"
        )
