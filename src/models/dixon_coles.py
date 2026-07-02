"""Modelo de resultado: Poisson bivariado con corrección Dixon-Coles (R1–R18).

Estima fuerzas ofensiva/defensiva por selección desde ``data/silver/matches.csv``
(contrato de la feature 2) por máxima verosimilitud ponderada con decaimiento
temporal (R3) y corrección de dependencia τ en marcadores bajos (R5), y predice
para un partido del Mundial 2026: probabilidades 1X2, matriz conjunta de
marcadores y top-k marcadores más probables (R13–R18). Localía parametrizada:
``h = 1`` en predicción SOLO si el local es anfitriona (``is_host``: MEX/USA/CAN).

Procesamiento 100 % offline: lee disco → escribe
``data/gold/dixon_coles_params.json``; no hay red, no se usa ``API_FOOTBALL_KEY``
ni ``Settings`` (mismo razonamiento que features 2 y 7). ``as_of_date`` SIEMPRE
inyectada (nunca ``now()`` implícito) — anti-leakage y reproducibilidad (R2, R10).
"""

from __future__ import annotations

import argparse
import json
import warnings
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path
from collections.abc import Callable
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

from ..ingestion.teams import is_host

# Rutas por defecto (parametrizables; R1, R11).
DEFAULT_SILVER_PATH = Path("data/silver/matches.csv")
DEFAULT_PARAMS_PATH = Path("data/gold/dixon_coles_params.json")
#: Ruta de parámetros v2 — NO pisa el v1 (R6 feature 12).
DEFAULT_PARAMS_PATH_V2 = Path("data/gold/dixon_coles_params_v2.json")

# Columnas del contrato silver consumidas (R1); el resto del contrato se ignora.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "match_id",
    "date",
    "home_code",
    "away_code",
    "home_goals",
    "away_goals",
    "neutral",
)

# Clip de tau antes del log: protección de dominio durante la optimización (R6).
TAU_MIN: float = 1e-10

# Días por año para el decaimiento temporal (R3).
_DAYS_PER_YEAR: float = 365.25


class SilverNotFoundError(RuntimeError):
    """Silver inexistente o sin las columnas requeridas del contrato (R1)."""


class NotFittedError(RuntimeError):
    """Parámetros no entrenados: archivo inexistente o JSON sin las claves del contrato (R12)."""


class UnknownTeamError(RuntimeError):
    """Código de equipo ausente de ``attack``/``defense`` en predicción (R18)."""


@dataclass(frozen=True)
class DCConfig:
    """Configuración inyectable del ajuste (design.md).

    - ``xi = 0.35``/año: óptimo del grid walk-forward 2024–2026 de la feature 5
      (17 configs, 2 510 partidos; log-loss 0.8641 vs 0.8943 del anterior 0.65).
      Aprobado por el usuario 2026-06-11. Con ``from_date = 2018-01-01`` los datos
      de 2018 pesan ~6 % (``exp(−0.35 × 8) ≈ 0.06``); ya no es despreciable pero
      sigue siendo una fracción manejable que aporta contexto histórico útil.
    - ``from_date = 2018-01-01``: conservado. La evidencia del grid se midió con esta
      ventana; recortarla invalidaría la comparación directa con los resultados del
      grid.
    - ``min_matches = 5``: umbral de ``low_data_teams`` (R8).
    - ``reg_lambda = 0.25``: ridge sobre ``att``/``def`` (shrinkage hacia 0, R8).
      Co-óptimo con ``xi = 0.35`` en el grid walk-forward (aprobado 2026-06-11).
    - ``max_iter = 1000``: inyectable para forzar no-convergencia en tests (R6).
    """

    xi: float = 0.35
    from_date: str = "2018-01-01"
    min_matches: int = 5
    reg_lambda: float = 0.25
    max_iter: int = 1000


@dataclass(frozen=True)
class TrainingData:
    """Arrays de entrenamiento precomputados una sola vez (R1–R4, R8).

    ``x``/``y``: goles local/visitante; ``w``: pesos de decaimiento (R3);
    ``h``: ``1 − neutral`` (R4); ``hi``/``ai``: índice del equipo local/visitante
    en el orden alfabético de ``teams`` (fancy indexing del objetivo, R6).
    """

    x: np.ndarray
    y: np.ndarray
    w: np.ndarray
    h: np.ndarray
    hi: np.ndarray
    ai: np.ndarray
    teams: tuple[str, ...]
    low_data_teams: tuple[str, ...]


@dataclass
class DixonColesParams:
    """Parámetros ajustados; campos = claves del JSON persistido (R11)."""

    as_of_date: str
    from_date: str
    xi: float
    mu: float
    home_advantage: float  # gamma
    rho: float
    attack: dict[str, float]
    defense: dict[str, float]
    n_matches: int
    n_teams: int
    min_matches: int
    reg_lambda: float
    low_data_teams: list[str]
    convergencia: dict[str, Any]


# Claves del contrato JSON (R11, R12) = campos del dataclass.
PARAMS_KEYS: tuple[str, ...] = tuple(f.name for f in fields(DixonColesParams))


@dataclass(frozen=True)
class MatchPrediction:
    """Salida de predicción (R14–R17): matriz conjunta expuesta para la feature 4."""

    lambda_home: float
    lambda_away: float
    matrix: np.ndarray
    prob_home: float
    prob_draw: float
    prob_away: float
    top_scores: tuple[tuple[int, int, float], ...]


def _validate_iso_date(value: str, name: str) -> None:
    """Valida formato estricto ``YYYY-MM-DD``; si no, ``ValueError`` claro (R2)."""
    try:
        ok = date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise ValueError(
            f"{name} debe tener formato YYYY-MM-DD; recibido: {value!r} (R2)"
        )


def decay_weights(dates: Iterable[str], as_of_date: str, xi: float) -> np.ndarray:
    """Pesos de decaimiento temporal ``w_i = exp(−xi·días(date_i, as_of_date)/365.25)`` (R3).

    ``días()`` = ``(as_of_date − date_i).days`` con ``date.fromisoformat``. Pesos
    estrictamente decrecientes con la antigüedad; con ``xi = 0`` valen exactamente 1.
    """
    as_of = date.fromisoformat(as_of_date)
    days = np.array(
        [(as_of - date.fromisoformat(d)).days for d in dates], dtype=float
    )
    return np.exp(-xi * days / _DAYS_PER_YEAR)


def match_rates(
    mu: float,
    gamma: float,
    att_home: float | np.ndarray,
    def_home: float | np.ndarray,
    att_away: float | np.ndarray,
    def_away: float | np.ndarray,
    h: float | np.ndarray,
) -> tuple[float | np.ndarray, float | np.ndarray]:
    """Tasas de gol del modelo — única fuente de la fórmula de R4 (ajuste y predicción).

    ``lambda_home = exp(mu + att_home − def_away + gamma·h)`` y
    ``lambda_away = exp(mu + att_away − def_home)``: ``gamma`` NUNCA interviene en
    ``lambda_away``, ni con ``h = 1`` (R4, R13). Vectorizable (acepta arrays).
    """
    lambda_home = np.exp(mu + att_home - def_away + gamma * h)
    lambda_away = np.exp(mu + att_away - def_home)
    return lambda_home, lambda_away


def tau_low_scores(
    x: int | np.ndarray,
    y: int | np.ndarray,
    lambda_h: float | np.ndarray,
    lambda_a: float | np.ndarray,
    rho: float,
) -> np.ndarray:
    """Corrección Dixon-Coles τ en marcadores bajos, definida EXACTAMENTE como R5.

    ``tau(0,0) = 1 − lambda_h·lambda_a·rho``; ``tau(0,1) = 1 + lambda_h·rho``;
    ``tau(1,0) = 1 + lambda_a·rho``; ``tau(1,1) = 1 − rho``; ``tau = 1`` en el
    resto. Pura y vectorizada con máscaras booleanas (``np.where``), sin bucles.
    """
    x = np.asarray(x)
    y = np.asarray(y)
    lh = np.asarray(lambda_h, dtype=float)
    la = np.asarray(lambda_a, dtype=float)
    tau = np.ones(np.broadcast(x, y, lh, la).shape)
    tau = np.where((x == 0) & (y == 0), 1.0 - lh * la * rho, tau)
    tau = np.where((x == 0) & (y == 1), 1.0 + lh * rho, tau)
    tau = np.where((x == 1) & (y == 0), 1.0 + la * rho, tau)
    tau = np.where((x == 1) & (y == 1), 1.0 - rho, tau)
    return tau


def _unpack_theta(
    theta: np.ndarray, n_teams: int
) -> tuple[float, float, float, np.ndarray, np.ndarray]:
    """Reparametrización suma-cero (R7): el último equipo alfabético se reconstruye.

    ``theta = [mu, gamma, rho, att_1..att_{n−1}, def_1..def_{n−1}]``;
    ``att_n = −Σ att_free`` y ``def_n = −Σ def_free`` vía ``np.append``.
    """
    mu = float(theta[0])
    gamma = float(theta[1])
    rho = float(theta[2])
    att_free = theta[3 : 3 + n_teams - 1]
    def_free = theta[3 + n_teams - 1 :]
    att = np.append(att_free, -att_free.sum())
    def_ = np.append(def_free, -def_free.sum())
    return mu, gamma, rho, att, def_


def _dtau_dlh_la_rho(
    x: np.ndarray,
    y: np.ndarray,
    lh: np.ndarray,
    la: np.ndarray,
    rho: float,
    tau: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Derivadas de log(τ) respecto a λ_home, λ_away y ρ — vectorizadas (R12, design.md).

    τ es polinómica en (λ_home, λ_away, ρ) en cada una de las 4 celdas bajas;
    sus derivadas parciales existen en forma cerrada::

        celda (0,0): τ = 1 − λ_h·λ_a·ρ
            ∂τ/∂λ_h = −λ_a·ρ,  ∂τ/∂λ_a = −λ_h·ρ,  ∂τ/∂ρ = −λ_h·λ_a

        celda (0,1): τ = 1 + λ_h·ρ
            ∂τ/∂λ_h = ρ,        ∂τ/∂λ_a = 0,         ∂τ/∂ρ = λ_h

        celda (1,0): τ = 1 + λ_a·ρ
            ∂τ/∂λ_h = 0,        ∂τ/∂λ_a = ρ,         ∂τ/∂ρ = λ_a

        celda (1,1): τ = 1 − ρ
            ∂τ/∂λ_h = 0,        ∂τ/∂λ_a = 0,         ∂τ/∂ρ = −1

        resto:       τ = 1       → derivadas = 0

    ``tau`` es el array ya recortado a ``TAU_MIN`` (el denominador de ∂log(τ)/∂·).
    Devuelve ``(d_log_tau_dlh, d_log_tau_dla, d_log_tau_drho)``, arrays del mismo
    tamaño que ``x``/``y``, con valor 0 fuera de las 4 celdas.

    Args:
        x: home goals array (float or int).
        y: away goals array (float or int).
        lh: lambda_home array.
        la: lambda_away array.
        rho: scalar correlation parameter.
        tau: clipped tau array (denominator for log-tau gradient).

    Returns:
        Tuple of three arrays: gradients of log(tau) w.r.t. lh, la, rho.
    """
    dtau_dlh = np.zeros_like(lh)
    dtau_dla = np.zeros_like(la)
    dtau_drho = np.zeros_like(lh)

    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)

    dtau_dlh = np.where(m00, -la * rho, dtau_dlh)
    dtau_dlh = np.where(m01, rho, dtau_dlh)
    # m10, m11: dtau_dlh = 0

    dtau_dla = np.where(m00, -lh * rho, dtau_dla)
    dtau_dla = np.where(m10, rho, dtau_dla)
    # m01, m11: dtau_dla = 0

    dtau_drho = np.where(m00, -lh * la, dtau_drho)
    dtau_drho = np.where(m01, lh, dtau_drho)
    dtau_drho = np.where(m10, la, dtau_drho)
    dtau_drho = np.where(m11, -1.0, dtau_drho)

    # Chain rule: ∂log(τ)/∂· = (1/τ)·∂τ/∂·
    d_log_tau_dlh = dtau_dlh / tau
    d_log_tau_dla = dtau_dla / tau
    d_log_tau_drho = dtau_drho / tau
    return d_log_tau_dlh, d_log_tau_dla, d_log_tau_drho


def _grad_nll_weighted(
    theta: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    h: np.ndarray,
    hi: np.ndarray,
    ai: np.ndarray,
    n_teams: int,
    reg_lambda: float,
) -> np.ndarray:
    """Gradiente analítico de ``nll_weighted`` — derivadas cerradas (R12, design.md).

    **Derivación completa** (documentada aquí como requiere R12):

    La NLL ponderada es::

        NLL(θ) = −Σ_i w_i [x_i·log(λ_h_i) − λ_h_i + y_i·log(λ_a_i) − λ_a_i + log(τ_i)]
                 + reg_lambda·(Σ_k att_k² + Σ_k def_k²)

    con ``λ_h = exp(μ + att[hi] − def[ai] + γ·h)`` y ``λ_a = exp(μ + att[ai] − def[hi])``.

    **Gradiente respecto a μ:**
        ∂NLL/∂μ = −Σ_i w_i [(x_i/λ_h_i − 1) + (y_i/λ_a_i − 1)
                              + ∂log(τ_i)/∂λ_h_i·λ_h_i + ∂log(τ_i)/∂λ_a_i·λ_a_i]

    **Gradiente respecto a γ (home_advantage):**
        ∂NLL/∂γ = −Σ_i w_i·h_i·[(x_i/λ_h_i − 1) + ∂log(τ_i)/∂λ_h_i·λ_h_i]

    **Gradiente respecto a ρ:**
        ∂NLL/∂ρ = −Σ_i w_i·∂log(τ_i)/∂ρ     (τ no depende de μ ni γ directamente)

    **Gradiente respecto a att_j (j = 0..n−2, libre):**

        att_n = −Σ_{j<n} att_j  →  ∂att_n/∂att_j = −1  (restricción suma-cero)

        Partido i contribuye a att_j si hi[i]==j (local, +1), ai[i]==j (visitante, +1),
        hi[i]==n−1 (local del equipo n, ∂att_n/∂att_j=−1), ai[i]==n−1 (visitante
        del equipo n, −1):

            ∂NLL/∂att_j = −Σ_{hi=j} w_i·[(x_i/λ_h − 1) + ∂log(τ)/∂λ_h·λ_h]
                          −Σ_{ai=j} w_i·[(y_i/λ_a − 1) + ∂log(τ)/∂λ_a·λ_a]
                          +Σ_{hi=n} w_i·[(x_i/λ_h − 1) + ∂log(τ)/∂λ_h·λ_h]
                          +Σ_{ai=n} w_i·[(y_i/λ_a − 1) + ∂log(τ)/∂λ_a·λ_a]
                          + 2·reg_lambda·(att_j − att_n)     ← ridge diferenciado

    **Gradiente respecto a def_j (j = 0..n−2, libre):**

        def_n = −Σ_{j<n} def_j  →  ∂def_n/∂def_j = −1

        Partido i: def[ai] aparece en λ_h (signo −1), def[hi] aparece en λ_a (signo −1):

            ∂NLL/∂def_j = +Σ_{ai=j} w_i·[(x_i/λ_h − 1) + ∂log(τ)/∂λ_h·λ_h]
                          +Σ_{hi=j} w_i·[(y_i/λ_a − 1) + ∂log(τ)/∂λ_a·λ_a]
                          −Σ_{ai=n} w_i·[(x_i/λ_h − 1) + ∂log(τ)/∂λ_h·λ_h]
                          −Σ_{hi=n} w_i·[(y_i/λ_a − 1) + ∂log(τ)/∂λ_a·λ_a]
                          + 2·reg_lambda·(def_j − def_n)     ← ridge diferenciado

    **Ridge sobre parámetros reconstruidos:** la penalización incluye att_n y def_n
    (como en ``nll_weighted``). Con la restricción suma-cero,
    ∂(Σ att_k²)/∂att_j = 2·att_j + 2·att_n·(∂att_n/∂att_j) = 2·(att_j − att_n).

    Args:
        theta: parameter vector ``[mu, gamma, rho, att_free..., def_free...]``.
        x: home goals array.
        y: away goals array.
        w: temporal decay weights.
        h: home field indicator (1 − neutral).
        hi: home team indices.
        ai: away team indices.
        n_teams: total number of teams.
        reg_lambda: ridge regularization coefficient.

    Returns:
        Gradient array of same shape as ``theta``.
    """
    theta = np.asarray(theta, dtype=float)
    mu, gamma, rho, att, def_ = _unpack_theta(theta, n_teams)
    lh, la = match_rates(mu, gamma, att[hi], def_[hi], att[ai], def_[ai], h)
    tau = np.maximum(tau_low_scores(x, y, lh, la, rho), TAU_MIN)

    # Partial derivatives of log(τ) w.r.t. λ_h, λ_a, ρ
    d_log_tau_dlh, d_log_tau_dla, d_log_tau_drho = _dtau_dlh_la_rho(x, y, lh, la, rho, tau)

    # Per-match partial derivatives of the log-likelihood (before weighting):
    #   ∂loglik_i/∂log(λ_h) = x_i − λ_h_i + ∂log(τ_i)/∂λ_h · λ_h_i
    #   ∂loglik_i/∂log(λ_a) = y_i − λ_a_i + ∂log(τ_i)/∂λ_a · λ_a_i
    # All θ-parameters enter λ_h and λ_a through their log, so each contributes
    # with the chain-rule factor equal to the coefficient in the exponent (±1).
    # Negating converts from ∂loglik to ∂NLL (before the ridge term).
    s_h = x - lh + d_log_tau_dlh * lh   # ∂loglik/∂log(λ_h), per match
    s_a = y - la + d_log_tau_dla * la   # ∂loglik/∂log(λ_a), per match

    n = n_teams - 1  # number of free parameters per block
    grad = np.empty_like(theta)

    # ∂NLL/∂μ: log(λ_h) and log(λ_a) both depend on μ with coefficient +1
    grad[0] = -(w * s_h).sum() - (w * s_a).sum()

    # ∂NLL/∂γ: only log(λ_h) depends on γ, coefficient = h_i
    grad[1] = -(w * h * s_h).sum()

    # ∂NLL/∂ρ: only through τ (τ does not depend on μ or γ directly)
    grad[2] = -(w * d_log_tau_drho).sum()

    # ∂NLL/∂att_j (free, j=0..n−1); att_n reconstructed as −Σ att_free
    # log(λ_h) depends on att[hi] with coeff +1 → contributes w·s_h when hi[i]=j
    # log(λ_a) depends on att[ai] with coeff +1 → contributes w·s_a when ai[i]=j
    # Chain rule for att_n: ∂att_n/∂att_j = −1 →
    #   additional −(w·s_h when hi[i]=n) and −(w·s_a when ai[i]=n)
    att_grad_full = np.zeros(n_teams)
    np.add.at(att_grad_full, hi, -w * s_h)   # loglik sign → negated for NLL
    np.add.at(att_grad_full, ai, -w * s_a)
    # Ridge: ∂(Σ_k att_k²)/∂att_j = 2·att_j + 2·att_n·(−1) = 2·(att_j − att_n)
    # Written per-team first, then projected: att_grad_full[k] += 2·λ·att[k]
    att_grad_full += 2.0 * reg_lambda * att
    # Projection onto free params: grad_j = att_grad_full[j] − att_grad_full[n]
    grad[3 : 3 + n] = att_grad_full[:n] - att_grad_full[n]

    # ∂NLL/∂def_j (free, j=0..n−1); def_n reconstructed as −Σ def_free
    # log(λ_h) = ... − def[ai] → coeff of def[ai] is −1 → contributes +w·s_h at ai[i]=j
    # log(λ_a) = ... − def[hi] → coeff of def[hi] is −1 → contributes +w·s_a at hi[i]=j
    def_grad_full = np.zeros(n_teams)
    np.add.at(def_grad_full, ai, w * s_h)    # def[ai] in λ_h with coeff −1 → NLL: +w·s_h
    np.add.at(def_grad_full, hi, w * s_a)    # def[hi] in λ_a with coeff −1 → NLL: +w·s_a
    # Ridge
    def_grad_full += 2.0 * reg_lambda * def_
    # Projection
    grad[3 + n :] = def_grad_full[:n] - def_grad_full[n]

    return grad


def nll_weighted(
    theta: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    h: np.ndarray,
    hi: np.ndarray,
    ai: np.ndarray,
    n_teams: int,
    reg_lambda: float,
) -> float:
    """Negativa de la log-verosimilitud ponderada, VECTORIZADA (R6).

    ``NLL = −Σ_i w_i·[x_i·log(lh_i) − lh_i + y_i·log(la_i) − la_i + log(tau_i)]
    + reg_lambda·(Σ att² + Σ def²)`` — sin bucles Python por partido: lambdas por
    fancy indexing (``att[hi]``, ``def_[ai]``, …) y τ por máscaras booleanas.
    ``tau`` se recorta a ``max(tau, 1e−10)`` antes del ``log`` (protección de
    dominio). Las constantes ``log(x_i!) + log(y_i!)`` se omiten (no dependen de
    ``theta``); el ``neg_log_lik`` reportado las excluye. La penalización ridge
    incluye los coeficientes reconstruidos (``att_n``, ``def_n``) — la suma cero
    se mantiene exacta (R7, R8).
    """
    theta = np.asarray(theta, dtype=float)
    _, gamma, rho, att, def_ = _unpack_theta(theta, n_teams)
    mu = theta[0]
    lh, la = match_rates(mu, gamma, att[hi], def_[hi], att[ai], def_[ai], h)
    tau = np.maximum(tau_low_scores(x, y, lh, la, rho), TAU_MIN)
    log_lik = w * (x * np.log(lh) - lh + y * np.log(la) - la + np.log(tau))
    penalty = reg_lambda * (np.sum(att**2) + np.sum(def_**2))
    return float(-log_lik.sum() + penalty)


def load_training_data(
    as_of_date: str,
    silver_path: Path | str = DEFAULT_SILVER_PATH,
    config: DCConfig = DCConfig(),
    importance_map: dict[str, float] | None = None,
    xg_target_map: dict[tuple[str, str], float] | None = None,
) -> TrainingData:
    """Carga silver, valida el contrato y precomputa los arrays de ajuste (R1–R4, R8).

    - Valida ``as_of_date``/``from_date`` como ``YYYY-MM-DD`` estricto (R2).
    - SI falta el archivo o alguna columna requerida → ``SilverNotFoundError``
      con la ruta/columna en el mensaje, sin escribir salida (R1).
    - Recorte estricto ``from_date <= date < as_of_date`` (anti-leakage, R2);
      SI deja 0 partidos → ``ValueError`` claro con la ventana.
    - Orden determinista ``(date, match_id)``; equipos alfabéticos (R10).
    - ``h = 1 − neutral`` en entrenamiento (R4); pesos de decaimiento (R3).
    - ``low_data_teams``: equipos con menos de ``min_matches`` partidos en el
      recorte (conteo sin ponderar, orden alfabético) (R8).
    - ``importance_map``: dict opcional ``{tournament: factor}`` (R1 feature 12).
      Cuando se proporciona, el peso combinado es
      ``w_i = exp(−ξ·Δaños) × importance_map.get(tournament_i, 1.0)``.
      Si es ``None`` o todos los factores son 1.0 → comportamiento idéntico a v1.
      El mapa se aplica DESPUÉS del recorte anti-fuga (R3) y SOLO a partidos
      dentro de la ventana ``[from_date, as_of_date)``.
    - ``xg_target_map``: dict opcional ``{(match_id, team_code): goal_target}``
      (R4 feature 15). Cuando se proporciona, sustituye el valor de goles para
      ``x`` (home team) o ``y`` (away team) donde haya entrada; donde no hay
      entrada se usan los goles reales. Con ``None`` → comportamiento idéntico
      a v1 (sin xG). Anti-fuga preservada: el mapa ya debe contener solo
      partidos con ``fecha < as_of_date`` (construido por ``proxy.build_goal_target_series``
      que respeta el filtro anti-fuga al pasar por ``load_training_data``).

    Args:
        as_of_date: Training cutoff date (YYYY-MM-DD). Anti-leakage gate (R2).
        silver_path: Path to silver matches CSV.
        config: Dixon-Coles configuration.
        importance_map: Optional dict mapping tournament name → importance factor.
            ``None`` or identity map → exact v1 behaviour.
        xg_target_map: Optional dict ``{(match_id, team_code): goal_target}``
            for the xG-blended objective series (R4, feature 15).
            ``None`` → use real goals (v1 behaviour, tol 1e-9).

    Returns:
        TrainingData with combined weights ``w = decay × importance``.
    """
    _validate_iso_date(as_of_date, "as_of_date")
    _validate_iso_date(config.from_date, "from_date")
    path = Path(silver_path)
    if not path.is_file():
        raise SilverNotFoundError(f"No existe el silver: {path} (R1)")
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SilverNotFoundError(
            f"Faltan columnas del contrato en {path}: {', '.join(missing)} (R1)"
        )
    df = df[(df["date"] >= config.from_date) & (df["date"] < as_of_date)]
    if df.empty:
        raise ValueError(
            f"0 partidos en la ventana [{config.from_date}, {as_of_date}) "
            f"de {path}: no hay nada que ajustar (R2)"
        )
    df = df.sort_values(["date", "match_id"], kind="mergesort").reset_index(drop=True)

    teams = tuple(sorted(set(df["home_code"]) | set(df["away_code"])))
    index = {code: i for i, code in enumerate(teams)}
    counts = pd.concat([df["home_code"], df["away_code"]]).value_counts()
    low_data = tuple(
        sorted(c for c in teams if int(counts.get(c, 0)) < config.min_matches)
    )

    neutral = df["neutral"]
    if neutral.dtype != bool:  # contrato: bool; tolera 'True'/'TRUE' como string
        neutral = neutral.astype(str).str.strip().str.lower().eq("true")

    # Pesos de decaimiento temporal (R3) — comportamiento v1 base
    decay_w = decay_weights(df["date"], as_of_date, config.xi)

    # Pesos de importancia (R1 feature 12): multiplicar por el factor del torneo.
    # Si importance_map es None o ausente → factor 1.0 para todos → idéntico a v1.
    if importance_map is not None:
        # La columna "tournament" puede o no existir en la versión mínima del contrato;
        # se tolera su ausencia usando factor 1.0 (nunca rompe calls previos).
        if "tournament" in df.columns:
            imp_factors = (
                df["tournament"]
                .astype(str)
                .map(lambda t: float(importance_map.get(t, 1.0)))
                .to_numpy(dtype=float)
            )
        else:
            imp_factors = np.ones(len(df), dtype=float)
        combined_w = decay_w * imp_factors
    else:
        combined_w = decay_w

    # Serie objetivo de goles (R4, feature 15): si xg_target_map está presente,
    # sustituye goles reales con la mezcla goal_target donde haya cobertura.
    # Con xg_target_map=None → x=home_goals, y=away_goals exactos → v1 (tol 1e-9).
    if xg_target_map is not None:
        x_vals = np.array(
            [
                float(
                    xg_target_map.get(
                        (str(row["match_id"]), str(row["home_code"])),
                        float(row["home_goals"]),
                    )
                )
                for _, row in df.iterrows()
            ],
            dtype=float,
        )
        y_vals = np.array(
            [
                float(
                    xg_target_map.get(
                        (str(row["match_id"]), str(row["away_code"])),
                        float(row["away_goals"]),
                    )
                )
                for _, row in df.iterrows()
            ],
            dtype=float,
        )
    else:
        x_vals = df["home_goals"].to_numpy(dtype=float)
        y_vals = df["away_goals"].to_numpy(dtype=float)

    return TrainingData(
        x=x_vals,
        y=y_vals,
        w=combined_w,
        h=1.0 - neutral.to_numpy(dtype=float),
        hi=df["home_code"].map(index).to_numpy(dtype=np.int64),
        ai=df["away_code"].map(index).to_numpy(dtype=np.int64),
        teams=teams,
        low_data_teams=low_data,
    )


def fit_dixon_coles(
    as_of_date: str,
    silver_path: Path | str = DEFAULT_SILVER_PATH,
    config: DCConfig = DCConfig(),
    use_analytic_jac: bool = True,
    importance_map: dict[str, float] | None = None,
    xg_target_map: dict[tuple[str, str], float] | None = None,
) -> DixonColesParams:
    """Ajusta ``(mu, gamma, rho, att, def)`` por MLE ponderada con L-BFGS-B (R1–R10, R12).

    - Punto inicial determinista (design.md): ``mu0 = log(media ponderada de goles
      por equipo y partido, recortada a ≥ 0.1)``, ``gamma0 = 0.2``, ``rho0 = 0``,
      ``att = def = 0``. Sin RNG ni reloj → reentrenamiento idéntico (R10).
    - Cotas: ``rho ∈ [−0.9, 0.9]``; resto sin cotas. Opciones fijas:
      ``maxiter = config.max_iter`` (default 1000),
      ``maxfun = config.max_iter · (dim(theta) + 1)`` (el gradiente numérico cuesta
      ``dim+1`` evaluaciones por iteración: así ``maxiter`` es el límite efectivo),
      ``ftol = 1e−12``, ``gtol = 1e−8``.
    - Registra ``convergencia = {success, n_iter, message, neg_log_lik}``; SI no
      converge → ``warnings.warn`` (RuntimeWarning) y devuelve los parámetros con
      el flag visible, sin abortar (R6).
    - Identificabilidad: ``sum(att) = 0`` y ``sum(def) = 0`` por reparametrización (R7).
    - ``use_analytic_jac=True`` (default, R12): pasa ``_grad_nll_weighted`` como
      ``jac=`` a ``scipy.optimize.minimize``; ``False`` conserva el camino numérico
      original (diferencias finitas de L-BFGS-B, sin cambio de comportamiento).
    - ``xg_target_map``: dict opcional ``{(match_id, team_code): goal_target}``
      para la serie objetivo mezclada xG (R4 feature 15). ``None`` → goles reales
      (v1 exacto, tol 1e-9).

    Args:
        as_of_date: Training cutoff date (YYYY-MM-DD).
        silver_path: Path to silver matches CSV.
        config: Dixon-Coles configuration.
        use_analytic_jac: Use analytical gradient (R12).
        importance_map: Optional tournament importance weights (R1 feature 12).
        xg_target_map: Optional xG-blended goal target map (R4 feature 15).

    Returns:
        DixonColesParams fitted by L-BFGS-B.
    """
    td = load_training_data(
        as_of_date,
        silver_path,
        config,
        importance_map=importance_map,
        xg_target_map=xg_target_map,
    )
    n_teams = len(td.teams)

    goals_per_team = float((td.w * (td.x + td.y)).sum() / (2.0 * td.w.sum()))
    mu0 = float(np.log(max(goals_per_team, 0.1)))
    theta0 = np.zeros(3 + 2 * (n_teams - 1))
    theta0[0] = mu0
    theta0[1] = 0.2  # gamma0
    theta0[2] = 0.0  # rho0
    bounds = [(None, None), (None, None), (-0.9, 0.9)] + [(None, None)] * (
        2 * (n_teams - 1)
    )

    # maxfun escalado a la dimensión: sin `jac`, L-BFGS-B aproxima el gradiente por
    # diferencias finitas (~n_params+1 evaluaciones de f por iteración); el default
    # de scipy (15000) agotaría las evaluaciones mucho antes de `maxiter` con
    # dimensiones reales (284 equipos → dim 569). Así `maxiter` vuelve a ser el
    # límite efectivo y `max_iter=1` sigue forzando no-convergencia en tests (R6).
    # Con jac analítico, maxfun ya no escala el coste, pero se conserva el mismo
    # valor para que max_iter=1 siga forzando no-convergencia en los tests (R6, R12).
    n_params = theta0.size
    nll_args = (td.x, td.y, td.w, td.h, td.hi, td.ai, n_teams, config.reg_lambda)
    jac = _grad_nll_weighted if use_analytic_jac else None
    result = minimize(
        nll_weighted,
        theta0,
        args=nll_args,
        jac=jac,
        method="L-BFGS-B",
        bounds=bounds,
        options={
            "maxiter": config.max_iter,
            "maxfun": config.max_iter * (n_params + 1),
            "ftol": 1e-12,
            "gtol": 1e-8,
        },
    )
    if not result.success:
        warnings.warn(
            f"El optimizador L-BFGS-B no convergió: {result.message} (R6)",
            RuntimeWarning,
            stacklevel=2,
        )
    convergencia: dict[str, Any] = {
        "success": bool(result.success),
        "n_iter": int(result.nit),
        "message": str(result.message),
        "neg_log_lik": float(result.fun),  # excluye las constantes factoriales
    }

    mu, gamma, rho, att, def_ = _unpack_theta(np.asarray(result.x, dtype=float), n_teams)
    return DixonColesParams(
        as_of_date=as_of_date,
        from_date=config.from_date,
        xi=config.xi,
        mu=mu,
        home_advantage=gamma,
        rho=rho,
        attack={code: float(a) for code, a in zip(td.teams, att)},
        defense={code: float(d) for code, d in zip(td.teams, def_)},
        n_matches=int(td.x.size),
        n_teams=n_teams,
        min_matches=config.min_matches,
        reg_lambda=config.reg_lambda,
        low_data_teams=list(td.low_data_teams),
        convergencia=convergencia,
    )


def save_params(
    params: DixonColesParams,
    path: Path | str = DEFAULT_PARAMS_PATH,
    extra_metadata: dict[str, Any] | None = None,
) -> Path:
    """Persiste los parámetros en JSON determinista (``sort_keys=True, indent=2``) (R11).

    ``extra_metadata`` permite añadir claves adicionales al JSON sin tocar el dataclass
    (usado por v2 para ``model_version`` e ``importance_config``, R6 feature 12).
    Las claves extra se fusionan en el doc; si hay conflicto, ``extra_metadata`` gana.

    Args:
        params: Trained Dixon-Coles parameters.
        path: Destination path (default: ``DEFAULT_PARAMS_PATH``).
        extra_metadata: Optional extra keys to merge into the JSON (R6 feature 12).

    Returns:
        Resolved output path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = asdict(params)
    if extra_metadata:
        doc.update(extra_metadata)
    path.write_text(
        json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_params(
    path: Path | str = DEFAULT_PARAMS_PATH,
    model_version: str | None = None,
) -> DixonColesParams:
    """Carga parámetros para predecir SIN reentrenar (R11, R6 feature 12).

    Acepta una ruta explícita o selecciona la ruta según ``model_version``:
    - ``model_version="dc-v1"`` → ``DEFAULT_PARAMS_PATH`` (default).
    - ``model_version="dc-v2"`` → ``DEFAULT_PARAMS_PATH_V2``.
    La ruta explícita siempre tiene prioridad sobre ``model_version``.

    Claves extra en el JSON (como ``model_version`` o ``importance_config``
    añadidas por v2) se ignoran para preservar retrocompatibilidad (R1 feature 12).

    SI el archivo no existe, el JSON es ilegible o falta alguna clave del contrato
    → ``NotFittedError`` con la ruta y el motivo (R12).

    Args:
        path: Explicit path to the parameters JSON. Takes precedence.
        model_version: ``"dc-v1"`` or ``"dc-v2"``; selects the default path if
            ``path`` is the module-level default.

    Returns:
        DixonColesParams loaded from the JSON file.
    """
    # Selección de ruta según model_version (sólo cuando no se proporcionó ruta
    # explícita distinta del default, para no cambiar comportamiento existente).
    resolved_path = Path(path)
    if model_version == "dc-v2" and resolved_path == DEFAULT_PARAMS_PATH:
        resolved_path = DEFAULT_PARAMS_PATH_V2

    if not resolved_path.is_file():
        raise NotFittedError(f"No existen parámetros entrenados en {resolved_path} (R12)")
    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotFittedError(
            f"JSON de parámetros ilegible en {resolved_path}: {exc} (R12)"
        ) from exc
    if not isinstance(data, dict):
        raise NotFittedError(
            f"JSON de parámetros inválido en {resolved_path}: se esperaba un objeto (R12)"
        )
    missing = [key for key in PARAMS_KEYS if key not in data]
    if missing:
        raise NotFittedError(
            f"Parámetros incompletos en {resolved_path}: faltan claves {', '.join(missing)} (R12)"
        )
    # Ignorar claves extra del JSON v2 (retrocompatibilidad, R1 feature 12)
    return DixonColesParams(**{key: data[key] for key in PARAMS_KEYS})


def score_matrix(
    lambda_home: float,
    lambda_away: float,
    rho: float,
    max_goals: int = 10,
) -> np.ndarray:
    """Matriz conjunta ``P(X = x, Y = y)`` para ``x, y ∈ {0..max_goals}`` (R14, R15).

    Función pura (reutilizable por la feature 4): outer de pmfs Poisson
    (``scipy.stats``, vectorizado), corrección τ multiplicando SOLO las 4 celdas
    bajas (R5), recorte de negativos a 0 (solo posible con ``rho`` extremo) y
    renormalización para que la matriz sume exactamente 1 (truncado a
    ``max_goals`` + τ preservan la suma solo en el soporte infinito).
    ``M[x, y]``: goles del local en filas.
    """
    goals = np.arange(max_goals + 1)
    matrix = np.outer(
        poisson.pmf(goals, lambda_home), poisson.pmf(goals, lambda_away)
    )
    low_x = np.array([0, 0, 1, 1])
    low_y = np.array([0, 1, 0, 1])
    matrix[low_x, low_y] *= tau_low_scores(low_x, low_y, lambda_home, lambda_away, rho)
    matrix = np.maximum(matrix, 0.0)
    return matrix / matrix.sum()


def predict_match(
    params: DixonColesParams,
    home_code: str,
    away_code: str,
    max_goals: int = 10,
    top_k: int = 5,
    form_factor: Callable[[str, str], tuple[float, float]] | None = None,
) -> MatchPrediction:
    """Predice un partido del Mundial 2026 (R13–R18).

    - ``h = 1`` SOLO SI ``is_host(home_code)`` (anfitrionas MEX/USA/CAN); ``h = 0``
      para cualquier otro local (sede neutral); ``gamma`` nunca afecta a
      ``lambda_away`` (R13).
    - Matriz conjunta renormalizada expuesta en la salida (R14, R15).
    - 1X2 desde la matriz: ``prob_home = tril(M, −1)`` (x > y),
      ``prob_draw = trace(M)``, ``prob_away = triu(M, 1)``; suman 1 (R16).
    - Top-k marcadores en orden descendente de probabilidad con desempate
      determinista por ``(home_goals, away_goals)`` ascendente (R17).
    - SI un código no existe en ``attack``/``defense`` → ``UnknownTeamError`` (R18).
    - ``form_factor``: callable opcional ``(home, away) → (mult_home, mult_away)``
      (Feature 16, R4). Si ``None`` o ``gamma=0`` el callable devuelve ``(1.0, 1.0)``
      → ``λ' = λ_DC · 1.0`` → predicción IDÉNTICA a v1 (tol 1e-9). NO toca la
      fuerza base del Dixon-Coles; aplica solo en inferencia.
    """
    for code in (home_code, away_code):
        if code not in params.attack or code not in params.defense:
            raise UnknownTeamError(
                f"Equipo desconocido en los parámetros entrenados: {code!r} (R18)"
            )
    h = 1.0 if is_host(home_code) else 0.0
    lambda_home, lambda_away = match_rates(
        params.mu,
        params.home_advantage,
        params.attack[home_code],
        params.defense[home_code],
        params.attack[away_code],
        params.defense[away_code],
        h,
    )
    lambda_home = float(lambda_home)
    lambda_away = float(lambda_away)

    # Feature 16: forma_reciente — multiplicador de inferencia (R4).
    # Con form_factor=None o γ=0 (→ devuelve (1.0,1.0)): λ inalteradas → v1 exacto.
    if form_factor is not None:
        mult_home, mult_away = form_factor(home_code, away_code)
        lambda_home *= mult_home
        lambda_away *= mult_away

    matrix = score_matrix(lambda_home, lambda_away, params.rho, max_goals)

    cells = [
        (gx, gy, float(matrix[gx, gy]))
        for gx in range(max_goals + 1)
        for gy in range(max_goals + 1)
    ]
    cells.sort(key=lambda c: (-c[2], c[0], c[1]))  # R17: desempate determinista
    return MatchPrediction(
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        matrix=matrix,
        prob_home=float(np.tril(matrix, -1).sum()),
        prob_draw=float(np.trace(matrix)),
        prob_away=float(np.triu(matrix, 1).sum()),
        top_scores=tuple(cells[:top_k]),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI opcional (design.md): entrena desde silver y escribe el JSON. Sin red."""
    parser = argparse.ArgumentParser(
        description="Ajusta el modelo Dixon-Coles desde data/silver/matches.csv (offline)."
    )
    parser.add_argument("--as-of-date", required=True, help="YYYY-MM-DD (inyectada, R2)")
    parser.add_argument("--from-date", default=DCConfig.from_date, help="YYYY-MM-DD")
    parser.add_argument("--xi", type=float, default=DCConfig.xi, help="decaimiento/año (R3)")
    parser.add_argument("--silver-path", default=str(DEFAULT_SILVER_PATH))
    parser.add_argument("--params-path", default=str(DEFAULT_PARAMS_PATH))
    args = parser.parse_args(argv)
    config = DCConfig(xi=args.xi, from_date=args.from_date)
    params = fit_dixon_coles(args.as_of_date, silver_path=args.silver_path, config=config)
    out = save_params(params, args.params_path)
    print(
        f"✅ Parámetros Dixon-Coles escritos en {out} "
        f"({params.n_matches} partidos, {params.n_teams} equipos, "
        f"convergencia={params.convergencia['success']})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI manual, sin red
    raise SystemExit(main())
