"""Mercado de corners O/U con modelo de tasa Poisson y shrinkage bayesiano (Feature 24).

Modelo propio separado del Dixon-Coles (los corners no salen de la distribucion de goles).
Flujo: silver (home/away_corners, date<as_of) -> team_corner_rates(shrinkage bayesiano)
       -> expected_corners -> corners_over_under (Poisson) -> CornersSummary.

Shrinkage: lambda = (n * media_equipo + k * mu_global) / (n + k).
Con n bajo (pocos partidos) la estimacion tira a la media global; conforme crece
n, domina la media del equipo. k=5 es la pseudo-cuenta por defecto.

Honestidad: con 3 partidos/equipo (WC2026 fase de grupos) el modelo produce predicciones
aproximadas a la media global + ajuste pequenio. Las predicciones mejoran con cada jornada.
n_matches_home/away cuantifica la muestra que sustenta la tasa de cada equipo.

Sin red, sin reloj, sin RNG. 100% offline y determinista.
Sin dependencias nuevas: numpy, scipy y pandas ya estan en el stack.

Public API:
    CornersConfig, CornersOULine, CornersSummary,
    team_corner_rates, expected_corners, corners_over_under, corners_summary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd


# ---------------------------------------------------------------------------
# Configuracion (R1, R3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CornersConfig:
    """Parametros del modelo de tasas de corners (R1, R3).

    Attributes:
        k: Shrinkage pseudo-count. Partidos equivalentes al prior global.
            k=5 significa que con n=5 partidos reales el prior pesa 50%.
            k=0 => media cruda (sin shrinkage). Default: 5.
        default_lines: Lineas O/U de corners. Default: (8.5, 9.5, 10.5, 11.5).
    """

    k: int = 5
    default_lines: tuple[float, ...] = (8.5, 9.5, 10.5, 11.5)


# ---------------------------------------------------------------------------
# Dataclasses de salida (R2, R3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CornersOULine:
    """Over/under para una linea de corners.

    Attributes:
        line: Linea de apuesta (ej. 9.5, 10.5).
        over: Probabilidad de superar la linea P(X > line) = P(X >= floor(line) + 1).
        under: Probabilidad de no superar la linea 1 - over.
    """

    line: float
    over: float
    under: float


@dataclass(frozen=True)
class CornersSummary:
    """Resumen completo del mercado de corners para un partido (R1-R3).

    Attributes:
        home_code: Codigo FIFA del equipo local.
        away_code: Codigo FIFA del equipo visitante.
        lambda_home: Corners esperados del equipo local (con shrinkage, R1).
        lambda_away: Corners esperados del equipo visitante.
        lambda_total: Corners totales esperados (lambda_home + lambda_away).
        mu_global: Media global de corners por equipo-partido (prior de shrinkage).
            0.0 si no hay datos de corners en el silver para date < as_of.
        k: Pseudo-cuenta de shrinkage usada (para el aviso de honestidad, R6).
        n_matches_home: Partidos con corners disponibles para el equipo local (R6).
        n_matches_away: Partidos con corners disponibles para el equipo visitante.
        total_ou: Over/under para corners totales del partido.
        home_ou: Over/under para corners del equipo local.
        away_ou: Over/under para corners del equipo visitante.
    """

    home_code: str
    away_code: str
    lambda_home: float
    lambda_away: float
    lambda_total: float
    mu_global: float
    k: int
    n_matches_home: int
    n_matches_away: int
    total_ou: tuple[CornersOULine, ...]
    home_ou: tuple[CornersOULine, ...]
    away_ou: tuple[CornersOULine, ...]


# ---------------------------------------------------------------------------
# Modelo de tasa (R1, R2)
# ---------------------------------------------------------------------------


def team_corner_rates(
    matches: pd.DataFrame,
    as_of: str,
    k: int = 5,
) -> tuple[dict[str, dict[str, float | int]], float]:
    """Estima tasas de corners por equipo con shrinkage bayesiano (R1).

    Solo usa partidos con date < as_of (anti-fuga, R1). Ignora filas con
    home_corners o away_corners nulos. Equipo sin partidos -> prior mu_global.

    Shrinkage: lambda = (n * media_equipo + k * mu_global) / (n + k).
    - n bajo => tasa tira a mu_global (prior global).
    - n grande => tasa converge a la media del equipo.

    Args:
        matches: Silver DataFrame con columnas date, home_code, away_code,
            home_corners, away_corners (nullable float).
        as_of: Fecha de corte YYYY-MM-DD. Solo date < as_of contribuye.
        k: Pseudo-cuenta de shrinkage (>= 0). Default: 5.

    Returns:
        Tuple (rates, mu_global) donde:
        - rates: dict {code: {"att": float, "dfn": float, "n": int}}.
          att = tasa de corners a favor (shrinkageada hacia mu_global).
          dfn = tasa de corners en contra / concedidos (shrinkageada).
          n = partidos con corners disponibles para este equipo.
        - mu_global: Media global de corners por equipo-partido (prior).
          0.0 si no hay datos validos.
    """
    # Anti-fuga: solo date < as_of (R1)
    filtered = matches[matches["date"] < as_of].copy()

    # Columnas requeridas
    if "home_corners" not in filtered.columns or "away_corners" not in filtered.columns:
        return {}, 0.0

    # Descartar filas con corners nulos (datos parciales del silver)
    filtered = filtered.dropna(subset=["home_corners", "away_corners"])
    if filtered.empty:
        return {}, 0.0

    # mu_global = media de todos los valores de corners (home + away)
    # = media de corners por equipo-partido (ambas orientaciones)
    all_corners: list[float] = (
        list(filtered["home_corners"].astype(float))
        + list(filtered["away_corners"].astype(float))
    )
    mu_global: float = sum(all_corners) / len(all_corners)

    # Acumular att y dfn por equipo
    team_att: dict[str, list[float]] = {}
    team_dfn: dict[str, list[float]] = {}

    for _, row in filtered.iterrows():
        home_code = str(row["home_code"])
        away_code = str(row["away_code"])
        hc = float(row["home_corners"])
        ac = float(row["away_corners"])

        # local: att = corners que genera, dfn = corners que concede al rival
        team_att.setdefault(home_code, []).append(hc)
        team_dfn.setdefault(home_code, []).append(ac)

        # visitante: att = corners que genera, dfn = corners que concede al rival
        team_att.setdefault(away_code, []).append(ac)
        team_dfn.setdefault(away_code, []).append(hc)

    rates: dict[str, dict[str, float | int]] = {}
    for code in set(team_att) | set(team_dfn):
        att_obs = team_att.get(code, [])
        dfn_obs = team_dfn.get(code, [])
        n = len(att_obs)  # mismo n para att y dfn (mismo conjunto de partidos)

        att_raw = sum(att_obs) / n if n > 0 else mu_global
        dfn_raw = sum(dfn_obs) / n if n > 0 else mu_global

        # Shrinkage bayesiano hacia mu_global (R1)
        # Con k=0 (sin prior): att = att_raw; con k grande: att -> mu_global
        denom = float(n + k)
        if denom > 0:
            att = (n * att_raw + k * mu_global) / denom
            dfn = (n * dfn_raw + k * mu_global) / denom
        else:
            att = mu_global
            dfn = mu_global

        rates[code] = {"att": att, "dfn": dfn, "n": n}

    return rates, mu_global


def expected_corners(
    rates: dict[str, dict[str, float | int]],
    home: str,
    away: str,
    mu_global: float,
) -> tuple[float, float, float]:
    """Combina tasa de ataque del local con defensa del visitante (R2).

    Formula multiplicativa (analoga a Dixon-Coles para goles):
      lambda_home = mu_global * (att_home / mu_global) * (dfn_away / mu_global)
                  = att_home * dfn_away / mu_global

      lambda_away = mu_global * (att_away / mu_global) * (dfn_home / mu_global)
                  = att_away * dfn_home / mu_global

    Equipo no visto en el silver -> mu_global como tasa (factor neutro = 1.0).
    Resultado clipado a > 0 para compatibilidad con Poisson (R2).

    Args:
        rates: Dict {code: {"att": float, "dfn": float}} de team_corner_rates.
        home: Codigo FIFA del equipo local.
        away: Codigo FIFA del equipo visitante.
        mu_global: Media global de corners por equipo-partido (prior).

    Returns:
        Tuple (lambda_home, lambda_away, lambda_total), todos > 0.
    """
    # Equipo no visto: usar mu_global como att y dfn (factor neutro = 1.0)
    att_home: float = float(rates.get(home, {}).get("att", mu_global))
    dfn_home: float = float(rates.get(home, {}).get("dfn", mu_global))
    att_away: float = float(rates.get(away, {}).get("att", mu_global))
    dfn_away: float = float(rates.get(away, {}).get("dfn", mu_global))

    # Sin datos globales: lambdas triviales
    if mu_global <= 0.0:
        return 0.01, 0.01, 0.02

    lam_home = att_home * dfn_away / mu_global
    lam_away = att_away * dfn_home / mu_global

    # Clip a > 0 (R2): garantiza compatibilidad con Poisson
    lam_home = max(lam_home, 1e-6)
    lam_away = max(lam_away, 1e-6)
    lam_total = lam_home + lam_away

    return lam_home, lam_away, lam_total


# ---------------------------------------------------------------------------
# Mercados Poisson (R3)
# ---------------------------------------------------------------------------


def _poisson_sf(k: int, lam: float) -> float:
    """P(X > k) con distribucion Poisson(lambda) — survival function (R3).

    Usa scipy.stats.poisson si disponible; fallback a suma directa de la PMF.
    Ambos son deterministas y sin red.

    Args:
        k: Umbral entero (P(X > k) = 1 - P(X <= k)).
        lam: Tasa Poisson (lambda > 0).

    Returns:
        Float en [0, 1].
    """
    try:
        from scipy.stats import poisson  # type: ignore[import-untyped]

        return float(poisson.sf(k, lam))
    except ImportError:
        # Fallback: CDF via acumulacion de PMF (determinista, sin scipy)
        if lam <= 0.0:
            return 0.0
        # P(X <= k) = sum_{i=0}^{k} e^{-lam} * lam^i / i!
        p = math.exp(-lam)
        cumsum = p
        for i in range(1, k + 1):
            p = p * lam / i
            cumsum += p
        return max(0.0, min(1.0, 1.0 - cumsum))


def corners_over_under(
    lam: float,
    lines: tuple[float, ...],
) -> dict[float, dict[str, float]]:
    """Deriva mercados over/under para un lambda Poisson dado (R3).

    Para cada linea L:
      P(over L) = P(X > L) = P(X >= floor(L) + 1) = 1 - P(X <= floor(L))
      P(under L) = 1 - P(over L)

    El resultado satisface over + under = 1.0 exactamente por construccion.

    Args:
        lam: Tasa Poisson esperada (lambda > 0).
        lines: Tupla de lineas O/U (ej. (8.5, 9.5, 10.5)).

    Returns:
        Dict {line: {"over": float, "under": float}} con over + under = 1.0.
    """
    result: dict[float, dict[str, float]] = {}
    for line in lines:
        # Para linea L: P(X > L) = poisson.sf(floor(L), lam)
        # Funciona correctamente para lineas k+0.5 (L=8.5 -> floor=8 -> P(X>=9))
        threshold = math.floor(line)
        over = _poisson_sf(threshold, lam)
        under = 1.0 - over
        result[line] = {"over": over, "under": under}
    return result


# ---------------------------------------------------------------------------
# Funcion de resumen principal (R1-R3, R6)
# ---------------------------------------------------------------------------


def corners_summary(
    matches: pd.DataFrame,
    home: str,
    away: str,
    as_of: str,
    config: CornersConfig | None = None,
) -> CornersSummary:
    """Calcula el resumen completo del mercado de corners para un partido (R1-R3, R6).

    Empaqueta tasas con shrinkage, lambdas esperados, O/U total y por equipo, y
    el numero de partidos que sustentan la estimacion (n_matches_home/away, R6).
    Con n bajo la prediccion tira a mu_global por diseno (honestidad, R6).

    Args:
        matches: Silver DataFrame con home_corners / away_corners (puede tener NaN).
        home: Codigo FIFA del equipo local.
        away: Codigo FIFA del equipo visitante.
        as_of: Fecha de corte YYYY-MM-DD (anti-fuga, R1).
        config: CornersConfig con k y lineas. None -> CornersConfig() por defecto.

    Returns:
        CornersSummary con lambdas, O/U total, O/U por equipo y n_matches.
        mu_global=0.0 si no hay datos de corners disponibles (degradacion, R6).
    """
    if config is None:
        config = CornersConfig()

    rates, mu_global = team_corner_rates(matches, as_of, k=config.k)

    lam_home, lam_away, lam_total = expected_corners(rates, home, away, mu_global)

    lines = tuple(sorted(config.default_lines))

    # O/U total usa lambda_total; por equipo usa lambda_home/lambda_away (R3)
    total_ou = tuple(
        CornersOULine(line=ln, **ou)
        for ln, ou in sorted(corners_over_under(lam_total, lines).items())
    )
    home_ou = tuple(
        CornersOULine(line=ln, **ou)
        for ln, ou in sorted(corners_over_under(lam_home, lines).items())
    )
    away_ou = tuple(
        CornersOULine(line=ln, **ou)
        for ln, ou in sorted(corners_over_under(lam_away, lines).items())
    )

    n_home = int(rates.get(home, {}).get("n", 0))
    n_away = int(rates.get(away, {}).get("n", 0))

    return CornersSummary(
        home_code=home,
        away_code=away,
        lambda_home=lam_home,
        lambda_away=lam_away,
        lambda_total=lam_total,
        mu_global=mu_global,
        k=config.k,
        n_matches_home=n_home,
        n_matches_away=n_away,
        total_ou=total_ou,
        home_ou=home_ou,
        away_ou=away_ou,
    )
