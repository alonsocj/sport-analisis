"""tests/test_cli_simulate_match.py — Feature 34: subcomando CLI simulate-match (R7/R8).

- R7 simulate-match escribe artefacto + salida  → test_cli_simulate_match_salida
- R7 --dead-rubber activa la amortiguación        → test_cli_simulate_match_dead_rubber
- R8 subcomandos previos intactos + nuevo         → test_simulate_match_en_parser
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest


def _dc_params():
    from src.models.dixon_coles import DixonColesParams
    attack = {"STRONG": 0.6, "WEAK": -0.4, "MID": 0.0}
    defense = {"STRONG": -0.5, "WEAK": 0.3, "MID": 0.0}
    return DixonColesParams(
        as_of_date="2026-07-15", from_date="2018-01-01", xi=0.35, mu=0.1,
        home_advantage=0.0, rho=-0.1, attack=attack, defense=defense,
        n_matches=1000, n_teams=len(attack), min_matches=5, reg_lambda=0.25,
        low_data_teams=[],
        convergencia={"success": True, "n_iter": 100, "message": "OK", "neg_log_lik": 1.0},
    )


def _read_e_goals(path: Path) -> float:
    with path.open(encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))
    return float(row["e_goals"])


def test_cli_simulate_match_salida(tmp_path: Path, monkeypatch, capsys):
    """R7: simulate-match --home/--away escribe el artefacto y sale 0."""
    from src import cli

    monkeypatch.setattr(cli, "load_params", lambda *a, **k: _dc_params())
    out = tmp_path / "final_sim.csv"
    code = cli.main([
        "simulate-match", "--home", "STRONG", "--away", "WEAK",
        "--n", "3000", "--seed", "1", "--out", str(out),
    ])
    assert code == 0
    assert out.is_file()
    with out.open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    for col in ("home", "away", "p_home", "p_away", "e_goals"):
        assert col in header
    captured = capsys.readouterr().out
    assert "STRONG" in captured and "WEAK" in captured


def test_cli_simulate_match_dead_rubber(tmp_path: Path, monkeypatch):
    """R7: --dead-rubber sube E[goles] vs baseline (misma seed)."""
    from src import cli

    monkeypatch.setattr(cli, "load_params", lambda *a, **k: _dc_params())
    base = tmp_path / "base.csv"
    damp = tmp_path / "damp.csv"
    cli.main(["simulate-match", "--home", "STRONG", "--away", "WEAK",
              "--n", "6000", "--seed", "2", "--out", str(base)])
    cli.main(["simulate-match", "--home", "STRONG", "--away", "WEAK",
              "--n", "6000", "--seed", "2", "--dead-rubber", "--out", str(damp)])
    assert _read_e_goals(damp) > _read_e_goals(base)


def test_simulate_match_en_parser():
    """R8: 'simulate-match' está en el parser y los subcomandos previos intactos."""
    from src.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(getattr(a, "choices", None), dict))
    cmds = set(sub.choices.keys())
    assert "simulate-match" in cmds
    # no-regresión: subcomandos previos clave siguen presentes
    for prev in ("simulate", "predict", "markets", "train", "ingest-ko", "build-ko-fixtures"):
        assert prev in cmds
