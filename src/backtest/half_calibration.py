"""src/backtest/half_calibration.py — Feature 32, R8: calibración de mercados por mitad.

Compara la calibración (log-loss) del mercado O/U por mitad usando el reparto de la
**señal** (share_1t por partido/rival) contra una **línea base naïve** (reparto fijo
45/55). La señal se ADOPTA solo si baja el log-loss frente al naïve.

Honestidad: la validación real requiere partidos WC2026 con cobertura per-mitad
poblada en el bronze (scrape real). Este módulo es el harness determinista y testeable;
alimentado con datos reales emite el veredicto de adopción.
"""

from __future__ import annotations

import math
from typing import Any

from src.markets.by_half import prob_over_half
from src.models.half_signal import split_lambda

_EPS = 1e-12


def logloss(probs: list[float], outcomes: list[int]) -> float:
    """Log-loss binario medio (R8).

    Args:
        probs: Probabilidades predichas P(evento) en [0, 1].
        outcomes: Resultados 0/1 (mismo largo que ``probs``).

    Returns:
        −mean(y·log p + (1−y)·log(1−p)), con clipping a [ε, 1−ε].
    """
    if not probs:
        raise ValueError("probs vacío")
    total = 0.0
    for p, y in zip(probs, outcomes):
        p = min(max(p, _EPS), 1 - _EPS)
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(probs)


def _over05_probs(matches: list[dict[str, Any]], share_fn) -> tuple[list[float], list[int]]:
    """P(over 0.5) por mitad (1T y 2T) y sus outcomes, para un reparto dado."""
    probs: list[float] = []
    outs: list[int] = []
    for m in matches:
        share_1t = share_fn(m)
        l1h, l2h = split_lambda(m["lambda_home"], share_1t)
        l1a, l2a = split_lambda(m["lambda_away"], share_1t)
        probs.append(prob_over_half(l1h, l1a, 0.5))
        outs.append(int(bool(m["over05_1t"])))
        probs.append(prob_over_half(l2h, l2a, 0.5))
        outs.append(int(bool(m["over05_2t"])))
    return probs, outs


def compare_half_calibration(
    matches: list[dict[str, Any]], naive_share_1t: float = 0.45
) -> dict[str, Any]:
    """Compara log-loss del O/U por mitad: señal (share_1t por partido) vs naïve fijo (R8).

    Args:
        matches: Lista de dicts con ``lambda_home``, ``lambda_away``, ``share_1t``
            (de la señal), ``over05_1t`` y ``over05_2t`` (outcomes reales).
        naive_share_1t: Reparto fijo de la línea base (default 0.45).

    Returns:
        ``{"signal_logloss", "naive_logloss", "signal_better", "n"}``.
    """
    p_sig, y = _over05_probs(matches, lambda m: m["share_1t"])
    p_naive, _ = _over05_probs(matches, lambda _m: naive_share_1t)
    ll_sig = logloss(p_sig, y)
    ll_naive = logloss(p_naive, y)
    return {
        "signal_logloss": ll_sig,
        "naive_logloss": ll_naive,
        "signal_better": ll_sig < ll_naive,
        "n": len(matches),
    }
