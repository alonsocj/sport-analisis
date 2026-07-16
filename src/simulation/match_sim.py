"""src/simulation/match_sim.py — Simulador Monte Carlo de un enfrentamiento fijo (F34, R4/R5/R6).

A diferencia de ``montecarlo.py`` (que simula el torneo completo grupos→campeón), este módulo
simula UN cruce concreto (p.ej. la Final o el 3er puesto) N veces y agrega un resultado
preciso: probabilidad de cada ganador, marcador modal de 90', top-k marcadores, reparto del
camino (90' / prórroga / penales), goles esperados, mercados (O/U + BTTS) y error MC.

Motor: la matriz de marcadores Dixon-Coles del cruce (analítica, vía ``score_matrix``) es la
fuente de muestreo. La prórroga se modela con las mismas λ escaladas ×1/3 (30' vs 90') y los
penales por Bernoulli ponderada por la fuerza del modelo — coherente con
``montecarlo.simulate_elimination_match``.

Amortiguación dead-rubber (F34, R3): si se pasa ``dead_rubber``, se encoge la ventaja de cada
equipo hacia la media del torneo y se aplica el bump de apertura ANTES de construir la matriz.
Con ``dead_rubber=None`` el comportamiento es el baseline exacto.

Determinismo (R4): ``numpy.random.default_rng(seed)``; sin red, sin reloj.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..models.dixon_coles import DixonColesParams, match_rates, score_matrix
from ..models.dead_rubber import DeadRubber, shrink_strengths, apply_openness
from ..ingestion.teams import is_host
from .montecarlo import MAX_GOALS, MIN_N_SIMULATIONS

DEFAULT_N: int = 50_000
DEFAULT_SEED: int = 42
ET_SCALE: float = 1.0 / 3.0  # 30' de prórroga vs 90' reglamentarios
TOP_K: int = 5


@dataclass
class MatchSimResult:
    """Resultado agregado de la simulación de un cruce fijo (R4).

    Attributes:
        home/away: Códigos FIFA.
        n/seed: Nº de simulaciones y semilla usada.
        p_home/p_away: Probabilidad de ganar el ENFRENTAMIENTO (incluye resolución de empate).
        p_home_reg/p_draw_reg/p_away_reg: Distribución del resultado en 90' (1X2 reglamentario).
        p_reg/p_et/p_pens: Reparto del camino de resolución.
        modal_score: Marcador más probable de 90' (home_goals, away_goals).
        top_scores: Top-k marcadores de 90' [(marcador, prob), ...] desc.
        e_goals: Goles totales esperados en 90'.
        markets: {"over_1.5", "over_2.5", "over_3.5", "btts"} (90').
        std_err: Error MC por métrica de proporción.
    """

    home: str
    away: str
    n: int
    seed: int
    p_home: float
    p_away: float
    p_home_reg: float
    p_draw_reg: float
    p_away_reg: float
    p_reg: float
    p_et: float
    p_pens: float
    modal_score: tuple[int, int]
    top_scores: list[tuple[tuple[int, int], float]]
    e_goals: float
    markets: dict[str, float]
    std_err: dict[str, float] = field(default_factory=dict)


def _lambdas(
    home: str,
    away: str,
    params: DixonColesParams,
    form_factor: Callable[[str, str], tuple[float, float]] | None,
    dead_rubber: DeadRubber | None,
) -> tuple[float, float]:
    """Computa (λ_home, λ_away) del cruce, con forma y dead-rubber opcionales."""
    if home not in params.attack or away not in params.attack:
        return 1.0, 1.0

    ah, dh = params.attack[home], params.defense[home]
    aa, da = params.attack[away], params.defense[away]

    # Dead-rubber (R3): encoge la ventaja hacia la media del torneo ANTES de las tasas.
    if dead_rubber is not None:
        mean_a = float(np.mean(list(params.attack.values())))
        mean_d = float(np.mean(list(params.defense.values())))
        ah, dh = shrink_strengths(ah, dh, mean_a, mean_d, dead_rubber.delta)
        aa, da = shrink_strengths(aa, da, mean_a, mean_d, dead_rubber.delta)

    h = 1.0 if is_host(home) else 0.0
    lh, la = match_rates(params.mu, params.home_advantage, ah, dh, aa, da, h)
    lh, la = float(lh), float(la)

    # Feature 16: factor de forma sobre las λ.
    if form_factor is not None:
        mh, ma = form_factor(home, away)
        lh, la = lh * mh, la * ma

    # Dead-rubber bump de apertura (más goles).
    if dead_rubber is not None:
        lh, la = apply_openness(lh, la, dead_rubber.kappa)

    return lh, la


def match_matrix(
    home: str,
    away: str,
    params: DixonColesParams,
    form_factor: Callable[[str, str], tuple[float, float]] | None = None,
    dead_rubber: DeadRubber | None = None,
) -> np.ndarray:
    """Matriz Dixon-Coles de marcadores de 90' del cruce (analítica; fuente de muestreo)."""
    lh, la = _lambdas(home, away, params, form_factor, dead_rubber)
    return score_matrix(lh, la, params.rho, MAX_GOALS)


def _sample_indices(matrix: np.ndarray, size: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Muestrea ``size`` marcadores (home_goals, away_goals) de la matriz, vectorizado."""
    side = matrix.shape[0]
    flat = matrix.flatten()
    flat = flat / flat.sum()
    idx = rng.choice(flat.size, size=size, p=flat)
    return idx // side, idx % side


def simulate_fixture(
    home: str,
    away: str,
    params: DixonColesParams,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    form_factor: Callable[[str, str], tuple[float, float]] | None = None,
    dead_rubber: DeadRubber | None = None,
    _allow_small_n: bool = False,
) -> MatchSimResult:
    """Simula N veces el cruce ``home`` vs ``away`` y agrega el resultado (R4, R5).

    Args:
        home/away: Códigos FIFA de los dos equipos del cruce.
        params: Parámetros Dixon-Coles entrenados.
        n: Nº de simulaciones (≥ MIN_N_SIMULATIONS salvo ``_allow_small_n``).
        seed: Semilla del RNG (inyectada, nunca del reloj).
        form_factor: Callable de forma (Feature 16) opcional.
        dead_rubber: Amortiguación de motivación (F34, R3) opcional — sólo el 3er puesto.
        _allow_small_n: Bypass del guard de n (solo tests).

    Returns:
        MatchSimResult agregado.

    Raises:
        ValueError: Si ``n`` < MIN_N_SIMULATIONS y no se permite n chica.
    """
    if not _allow_small_n and n < MIN_N_SIMULATIONS:
        raise ValueError(f"n debe ser >= {MIN_N_SIMULATIONS}, se recibió n={n}.")

    lh, la = _lambdas(home, away, params, form_factor, dead_rubber)
    matrix = score_matrix(lh, la, params.rho, MAX_GOALS)
    et_matrix = score_matrix(lh * ET_SCALE, la * ET_SCALE, params.rho, MAX_GOALS)

    prob_home_an = float(np.tril(matrix, -1).sum())
    prob_away_an = float(np.triu(matrix, 1).sum())

    rng = np.random.default_rng(seed)

    # --- 90' reglamentario (vectorizado) ---
    hg, ag = _sample_indices(matrix, n, rng)
    reg_home = hg > ag
    reg_away = hg < ag
    reg_draw = hg == ag

    n_home_reg = int(reg_home.sum())
    n_away_reg = int(reg_away.sum())
    n_draw = int(reg_draw.sum())

    # Camino de resolución
    winners_home = n_home_reg
    winners_away = n_away_reg
    n_et = 0
    n_pens = 0

    if n_draw > 0:
        # --- Prórroga (30', λ×1/3) para los empatados ---
        ehg, eag = _sample_indices(et_matrix, n_draw, rng)
        et_home = ehg > eag
        et_away = ehg < eag
        et_draw = ehg == eag

        winners_home += int(et_home.sum())
        winners_away += int(et_away.sum())
        n_et = int(et_home.sum()) + int(et_away.sum())

        n_still_draw = int(et_draw.sum())
        if n_still_draw > 0:
            # --- Penales: Bernoulli ponderada por la fuerza del modelo ---
            total = prob_home_an + prob_away_an
            p_home_pens = 0.5 if total <= 0 else prob_home_an / total
            pens = rng.random(n_still_draw) < p_home_pens
            n_pens_home = int(pens.sum())
            winners_home += n_pens_home
            winners_away += n_still_draw - n_pens_home
            n_pens = n_still_draw

    # --- Agregación ---
    p_home = winners_home / n
    p_away = winners_away / n
    p_home_reg = n_home_reg / n
    p_draw_reg = n_draw / n
    p_away_reg = n_away_reg / n
    p_reg = (n_home_reg + n_away_reg) / n
    p_et = n_et / n
    p_pens = n_pens / n

    # Histograma de marcadores de 90' → modal + top-k
    totals = hg + ag
    e_goals = float(totals.mean())
    pairs, counts = np.unique(np.stack([hg, ag], axis=1), axis=0, return_counts=True)
    order = np.argsort(-counts)
    top_scores = [
        ((int(pairs[i, 0]), int(pairs[i, 1])), float(counts[i] / n))
        for i in order[:TOP_K]
    ]
    modal_score = top_scores[0][0]

    # Mercados de 90'
    markets = {
        "over_1.5": float((totals >= 2).mean()),
        "over_2.5": float((totals >= 3).mean()),
        "over_3.5": float((totals >= 4).mean()),
        "btts": float(((hg >= 1) & (ag >= 1)).mean()),
    }

    # Error MC por proporción
    def se(p: float) -> float:
        return float(np.sqrt(max(p * (1.0 - p), 0.0) / n))

    std_err = {
        "p_home": se(p_home),
        "p_away": se(p_away),
        "p_home_reg": se(p_home_reg),
        "p_draw_reg": se(p_draw_reg),
        "p_away_reg": se(p_away_reg),
        "p_reg": se(p_reg),
        "p_et": se(p_et),
        "p_pens": se(p_pens),
        **{k: se(v) for k, v in markets.items()},
    }

    return MatchSimResult(
        home=home,
        away=away,
        n=n,
        seed=seed,
        p_home=p_home,
        p_away=p_away,
        p_home_reg=p_home_reg,
        p_draw_reg=p_draw_reg,
        p_away_reg=p_away_reg,
        p_reg=p_reg,
        p_et=p_et,
        p_pens=p_pens,
        modal_score=modal_score,
        top_scores=top_scores,
        e_goals=e_goals,
        markets=markets,
        std_err=std_err,
    )


# ---------------------------------------------------------------------------
# Persistencia (R6)
# ---------------------------------------------------------------------------

def assert_under_data(path: Path | str, root: Path | str = Path.cwd()) -> Path:
    """Verifica que ``path`` cae bajo ``root/data/`` (guard de escritura R6).

    Raises:
        ValueError: Si la ruta resuelta no está bajo ``root/data``.
    """
    path = Path(path).resolve()
    data_root = (Path(root) / "data").resolve()
    try:
        path.relative_to(data_root)
    except ValueError as exc:
        raise ValueError(f"Escritura sólo permitida bajo {data_root}, se recibió {path}.") from exc
    return path


def write_sim_result(res: MatchSimResult, path: Path | str) -> Path:
    """Persiste ``res`` como CSV plano (una fila resumen + top marcadores) (R6)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    top_str = ";".join(f"{h}-{a}:{p:.4f}" for (h, a), p in res.top_scores)
    header = [
        "home", "away", "n", "seed",
        "p_home", "p_away",
        "p_home_reg", "p_draw_reg", "p_away_reg",
        "p_reg", "p_et", "p_pens",
        "modal_home", "modal_away", "e_goals",
        "over_1.5", "over_2.5", "over_3.5", "btts",
        "top_scores",
    ]
    row = [
        res.home, res.away, res.n, res.seed,
        f"{res.p_home:.6f}", f"{res.p_away:.6f}",
        f"{res.p_home_reg:.6f}", f"{res.p_draw_reg:.6f}", f"{res.p_away_reg:.6f}",
        f"{res.p_reg:.6f}", f"{res.p_et:.6f}", f"{res.p_pens:.6f}",
        res.modal_score[0], res.modal_score[1], f"{res.e_goals:.4f}",
        f"{res.markets['over_1.5']:.6f}", f"{res.markets['over_2.5']:.6f}",
        f"{res.markets['over_3.5']:.6f}", f"{res.markets['btts']:.6f}",
        top_str,
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerow(row)
    return path
