"""tests/test_senal_por_mitad_backtest.py — Feature 32, R8: backtest calibración por mitad.

Trazabilidad:
- test_logloss_basico                → R8 (log-loss determinista)
- test_backtest_por_mitad_calibra_vs_naive → R8 (la señal bate al naive 45/55 cuando
  la realidad está sesgada por mitad y la señal la captura)
"""

from __future__ import annotations

import math

from src.backtest.half_calibration import compare_half_calibration, logloss


def test_logloss_basico():
    """R8: log-loss = −mean(y·log p + (1−y)·log(1−p))."""
    ll = logloss([0.9, 0.2], [1, 0])
    expect = -0.5 * (math.log(0.9) + math.log(0.8))
    assert abs(ll - expect) < 1e-9


def test_backtest_por_mitad_calibra_vs_naive():
    """R8: si la realidad carga el 2T y la señal lo captura, la señal bate al naive 45/55."""
    # 4 partidos donde SIEMPRE hay gol en 2T y casi nunca en 1T; la señal lo sabe
    # (share_1t bajo), el naive reparte 0.45/0.55 fijo.
    matches = []
    for _ in range(4):
        matches.append(
            {
                "lambda_home": 1.4,
                "lambda_away": 1.0,
                "share_1t": 0.15,       # señal: casi todo el juego es de 2T
                "over05_1t": False,     # realidad: sin gol en 1T
                "over05_2t": True,      # realidad: gol en 2T
            }
        )
    rep = compare_half_calibration(matches, naive_share_1t=0.45)
    assert rep["signal_logloss"] < rep["naive_logloss"]
    assert rep["signal_better"] is True
    assert rep["n"] == 4
