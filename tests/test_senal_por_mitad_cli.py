"""tests/test_senal_por_mitad_cli.py — Feature 32, R6/R7: flag --by-half + no-regresión.

100% offline: main(argv) en proceso con params sintéticos en tmp_path.
Trazabilidad:
- test_flag_off_equivalencia    → R6 (flag OFF = salida idéntica, sin clave by_half)
- test_no_regresion_markets_previos → R6 (markets sin flag intacto)
- test_cli_subcomandos_intactos → R7 (no se añade subcomando; --by-half es flag)
- test_cli_half_markets_salida  → R7 (con --by-half la salida trae los mercados por mitad)
"""

from __future__ import annotations

import json
from pathlib import Path

import src.cli as cli


def _write_params(tmp_path: Path) -> Path:
    doc = {
        "as_of_date": "2026-06-01", "from_date": "2018-01-01", "xi": 0.65, "mu": 0.1,
        "home_advantage": 0.3, "rho": -0.08,
        "attack": {"ARG": 0.40, "BRA": -0.10}, "defense": {"ARG": 0.30, "BRA": 0.20},
        "n_matches": 240, "n_teams": 2, "min_matches": 5, "reg_lambda": 1.0,
        "low_data_teams": [],
        "convergencia": {"success": True, "n_iter": 50, "message": "ok", "neg_log_lik": 100.0},
    }
    p = tmp_path / "dixon_coles_params.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _run(argv, capsys):
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return rc, out


def test_flag_off_equivalencia(tmp_path, capsys):
    """R6: sin --by-half la salida JSON es idéntica (no aparece la clave by_half)."""
    params = _write_params(tmp_path)
    rc, out = _run(["markets", "ARG", "BRA", "--params", str(params), "--json"], capsys)
    assert rc == 0
    doc = json.loads(out)
    assert "by_half" not in doc


def test_no_regresion_markets_previos(tmp_path, capsys):
    """R6: el default de --by-half es False (comportamiento previo intacto)."""
    ns = cli.build_parser().parse_args(["markets", "ARG", "BRA"])
    assert ns.by_half is False


def test_cli_subcomandos_intactos(tmp_path, capsys):
    """R7: --by-half es un flag de 'markets', NO un subcomando nuevo."""
    import pytest

    parser = cli.build_parser()
    # 'markets ARG BRA --by-half' parsea OK
    ns = parser.parse_args(["markets", "ARG", "BRA", "--by-half"])
    assert ns.by_half is True
    # 'half-markets' NO existe como subcomando
    with pytest.raises(SystemExit):
        parser.parse_args(["half-markets", "ARG", "BRA"])


def test_cli_half_markets_salida(tmp_path, capsys):
    """R7: con --by-half --json la salida trae los mercados por mitad (O/U 1T/2T, marca 2T, gol 76-90)."""
    params = _write_params(tmp_path)
    rc, out = _run(
        ["markets", "ARG", "BRA", "--params", str(params), "--by-half", "--json"], capsys
    )
    assert rc == 0
    doc = json.loads(out)
    bh = doc["by_half"]
    assert "ou_1t" in bh and "ou_2t" in bh
    assert "marca_2t" in bh and "gol_76_90" in bh
    # probabilidades válidas
    assert 0.0 <= bh["gol_76_90"] <= 1.0
    assert 0.0 <= bh["marca_2t"]["home"] <= 1.0


def test_by_half_ajuste_rival(tmp_path):
    """R4/R5: con señal gold donde el rival se cae en 2T, el reparto es ajuste_rival y
    el equipo local marca MÁS en 2T que con el reparto prior."""
    from src.cli import _by_half_markets_dict
    from src.models.dixon_coles import load_params

    params = load_params(str(_write_params(tmp_path)))
    # BRA (rival) concede casi todo en 2T; ARG reparte parejo
    signal = {
        "ARG": {"att": {"1T": 0.5, "2T": 0.5}, "def": {"1T": 0.5, "2T": 0.5}},
        "BRA": {"att": {"1T": 0.5, "2T": 0.5}, "def": {"1T": 0.2, "2T": 0.8}},
    }
    d_sig = _by_half_markets_dict(params, "ARG", "BRA", signal=signal)
    d_prior = _by_half_markets_dict(params, "ARG", "BRA", signal=None)
    assert d_sig["reparto"] == "ajuste_rival"
    assert d_prior["reparto"] == "prior_liga"
    assert d_sig["marca_2t"]["home"] > d_prior["marca_2t"]["home"]
