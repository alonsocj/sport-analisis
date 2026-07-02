"""Motor generico de conteo O/U (tarjetas, tiros, tiros a puerta) — Feature 25.

Parametriza la misma maquinaria de shrinkage bayesiano + Poisson O/U que corners.py
(Feature 24) sobre cualquier estadistica de conteo del silver. Soporta tres stats:
- cards   (tarjetas)          : columnas home/away_cards;
                                muy ruidoso (no hay dato de arbitro).
- shots   (tiros)             : columnas home/away_shots.
- sot     (tiros a puerta)    : columnas home/away_shots_on_target.

Flujo: silver (home/away_<stat>, date<as_of) -> count_rates(shrinkage) ->
       expected_counts -> count_over_under(Poisson) -> CountSummary.

Honestidad extra: las tarjetas dependen del arbitro (no disponible), por lo que
se etiquetan con una nota de ruido elevado. El modulo NO modifica corners.py;
importa solo el helper Poisson privado (_poisson_sf) para evitar duplicacion.

Sin red, sin reloj, sin RNG. 100 % offline y determinista.
Sin dependencias nuevas: numpy, scipy y pandas ya estan en el stack.

Public API:
    STAT_SPECS, StatSpec, CountConfig, CountOULine, CountSummary,
    count_rates, expected_counts, count_over_under, count_summary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .corners import _poisson_sf  # helper Poisson sin duplicar codigo


# ---------------------------------------------------------------------------
# Especificacion por stat (R1, R2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatSpec:
    """Especificacion de una estadistica de conteo (R1, R2).

    Attributes:
        silver_col_base: Sufijo de la columna silver (home/away_{base}).
        lines_default: Lineas O/U por defecto para esta estadistica.
        label: Etiqueta legible para la UI y el CLI.
        noisy_note: Nota de ruido opcional (no None solo para tarjetas, R4).
    """

    silver_col_base: str
    lines_default: tuple[float, ...]
    label: str
    noisy_note: str | None


#: Dict de especificaciones por clave de stat (cards, shots, sot).
STAT_SPECS: dict[str, StatSpec] = {
    "cards": StatSpec(
        silver_col_base="cards",
        lines_default=(2.5, 3.5, 4.5),
        label="Tarjetas",
        noisy_note=(
            "Depende del arbitro (no disponible) — muy ruidoso; "
            "usar con precaucion."
        ),
    ),
    "shots": StatSpec(
        silver_col_base="shots",
        lines_default=(20.5, 24.5, 28.5),
        label="Tiros",
        noisy_note=None,
    ),
    "sot": StatSpec(
        silver_col_base="shots_on_target",
        lines_default=(6.5, 8.5, 10.5),
        label="Tiros a puerta (SoT)",
        noisy_note=None,
    ),
}


# ---------------------------------------------------------------------------
# Configuracion (R1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CountConfig:
    """Parametros del motor de conteo generico (R1).

    Attributes:
        k: Pseudo-cuenta de shrinkage. Default: 5.
        lines: Lineas O/U custom. None -> usa STAT_SPECS[stat].lines_default.
    """

    k: int = 5
    lines: tuple[float, ...] | None = None


# ---------------------------------------------------------------------------
# Dataclasses de salida (R1, R2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CountOULine:
    """Over/under para una linea de la estadistica de conteo (R2).

    Attributes:
        line: Linea de apuesta (ej. 2.5, 3.5).
        over: Probabilidad de superar la linea P(X > line).
        under: Probabilidad de no superar la linea 1 - over.
    """

    line: float
    over: float
    under: float


@dataclass(frozen=True)
class CountSummary:
    """Resumen completo del mercado de conteo para un partido (R1, R2).

    Attributes:
        home_code: Codigo FIFA del equipo local.
        away_code: Codigo FIFA del equipo visitante.
        stat: Clave de la estadistica ('cards', 'shots', 'sot').
        label: Etiqueta legible de la estadistica.
        noisy_note: Nota de ruido (no None solo para tarjetas, R4).
        lambda_home: Valor esperado del equipo local (con shrinkage).
        lambda_away: Valor esperado del equipo visitante.
        lambda_total: Total esperado (lambda_home + lambda_away).
        mu_global: Media global por equipo-partido (prior de shrinkage).
            0.0 si no hay datos validos (degradacion, R1).
        k: Pseudo-cuenta de shrinkage usada.
        n_matches_home: Partidos con la stat disponible para el local.
        n_matches_away: Partidos con la stat disponible para el visitante.
        total_ou: Over/under para el total del partido.
        home_ou: Over/under para el equipo local.
        away_ou: Over/under para el equipo visitante.
    """

    home_code: str
    away_code: str
    stat: str
    label: str
    noisy_note: str | None
    lambda_home: float
    lambda_away: float
    lambda_total: float
    mu_global: float
    k: int
    n_matches_home: int
    n_matches_away: int
    total_ou: tuple[CountOULine, ...]
    home_ou: tuple[CountOULine, ...]
    away_ou: tuple[CountOULine, ...]


# ---------------------------------------------------------------------------
# Modelo de tasa (R1)
# ---------------------------------------------------------------------------


def count_rates(
    matches: pd.DataFrame,
    as_of: str,
    stat: str,
    k: int = 5,
) -> tuple[dict[str, dict[str, float | int]], float]:
    """Estima tasas de la estadistica por equipo con shrinkage bayesiano (R1).

    Solo usa partidos con date < as_of (anti-fuga, R1). Ignora filas con la
    stat nula. Equipo sin partidos -> prior mu_global. Stat no reconocida o
    columnas ausentes -> retorna ({}, 0.0) (degradacion, R1).

    Shrinkage: lambda = (n * media_equipo + k * mu_global) / (n + k).
    - n bajo => tasa tira a mu_global (prior global).
    - n grande => tasa converge a la media del equipo.

    Args:
        matches: Silver DataFrame con columnas date, home_code, away_code y
            home/away_{base} (nullable float).
        as_of: Fecha de corte YYYY-MM-DD. Solo date < as_of contribuye.
        stat: Clave de la estadistica en STAT_SPECS ('cards', 'shots', 'sot').
        k: Pseudo-cuenta de shrinkage (>= 0). Default: 5.

    Returns:
        Tuple (rates, mu_global) donde:
        - rates: dict {code: {"att": float, "dfn": float, "n": int}}.
        - mu_global: Media global por equipo-partido. 0.0 si sin datos.
    """
    if stat not in STAT_SPECS:
        return {}, 0.0

    spec = STAT_SPECS[stat]
    home_col = f"home_{spec.silver_col_base}"
    away_col = f"away_{spec.silver_col_base}"

    # Anti-fuga: solo date < as_of (R1)
    filtered = matches[matches["date"] < as_of].copy()

    if home_col not in filtered.columns or away_col not in filtered.columns:
        return {}, 0.0

    # Descartar filas con la stat nula
    filtered = filtered.dropna(subset=[home_col, away_col])
    if filtered.empty:
        return {}, 0.0

    # mu_global = media de todos los valores (home + away) por equipo-partido
    all_vals: list[float] = (
        list(filtered[home_col].astype(float))
        + list(filtered[away_col].astype(float))
    )
    mu_global: float = sum(all_vals) / len(all_vals)

    # Acumular att y dfn por equipo
    team_att: dict[str, list[float]] = {}
    team_dfn: dict[str, list[float]] = {}

    for _, row in filtered.iterrows():
        home_code = str(row["home_code"])
        away_code = str(row["away_code"])
        h_val = float(row[home_col])
        a_val = float(row[away_col])

        # local: att = stat que genera, dfn = stat que concede al rival
        team_att.setdefault(home_code, []).append(h_val)
        team_dfn.setdefault(home_code, []).append(a_val)

        # visitante: att = stat que genera, dfn = stat que concede al rival
        team_att.setdefault(away_code, []).append(a_val)
        team_dfn.setdefault(away_code, []).append(h_val)

    rates: dict[str, dict[str, float | int]] = {}
    for code in set(team_att) | set(team_dfn):
        att_obs = team_att.get(code, [])
        dfn_obs = team_dfn.get(code, [])
        n = len(att_obs)

        att_raw = sum(att_obs) / n if n > 0 else mu_global
        dfn_raw = sum(dfn_obs) / n if n > 0 else mu_global

        # Shrinkage bayesiano hacia mu_global (R1)
        denom = float(n + k)
        if denom > 0:
            att = (n * att_raw + k * mu_global) / denom
            dfn = (n * dfn_raw + k * mu_global) / denom
        else:
            att = mu_global
            dfn = mu_global

        rates[code] = {"att": att, "dfn": dfn, "n": n}

    return rates, mu_global


# ---------------------------------------------------------------------------
# Lambdas esperados (R1, R2)
# ---------------------------------------------------------------------------


def expected_counts(
    rates: dict[str, dict[str, float | int]],
    home: str,
    away: str,
    mu_global: float,
) -> tuple[float, float, float]:
    """Combina tasa de ataque del local con defensa del visitante (R1, R2).

    Formula multiplicativa (espeja la de corners.py):
      lambda_home = att_home * dfn_away / mu_global
      lambda_away = att_away * dfn_home / mu_global

    Equipo no visto en el silver -> mu_global como tasa (factor neutro = 1.0).
    Resultado clipado a > 0 para compatibilidad con Poisson.

    Args:
        rates: Dict {code: {"att": float, "dfn": float}} de count_rates.
        home: Codigo FIFA del equipo local.
        away: Codigo FIFA del equipo visitante.
        mu_global: Media global por equipo-partido (prior).

    Returns:
        Tuple (lambda_home, lambda_away, lambda_total), todos > 0.
    """
    att_home: float = float(rates.get(home, {}).get("att", mu_global))
    dfn_home: float = float(rates.get(home, {}).get("dfn", mu_global))
    att_away: float = float(rates.get(away, {}).get("att", mu_global))
    dfn_away: float = float(rates.get(away, {}).get("dfn", mu_global))

    # Sin datos globales: lambdas triviales (degradacion, R1)
    if mu_global <= 0.0:
        return 0.01, 0.01, 0.02

    lam_home = att_home * dfn_away / mu_global
    lam_away = att_away * dfn_home / mu_global

    lam_home = max(lam_home, 1e-6)
    lam_away = max(lam_away, 1e-6)
    lam_total = lam_home + lam_away

    return lam_home, lam_away, lam_total


# ---------------------------------------------------------------------------
# Mercados Poisson (R2)
# ---------------------------------------------------------------------------


def count_over_under(
    lam: float,
    lines: tuple[float, ...],
) -> dict[float, dict[str, float]]:
    """Deriva mercados over/under para un lambda Poisson dado (R2).

    Para cada linea L:
      P(over L) = P(X > L) = P(X >= floor(L) + 1) = 1 - P(X <= floor(L))
      P(under L) = 1 - P(over L)

    El resultado satisface over + under = 1.0 exactamente por construccion.

    Args:
        lam: Tasa Poisson esperada (lambda > 0).
        lines: Tupla de lineas O/U (ej. (2.5, 3.5, 4.5)).

    Returns:
        Dict {line: {"over": float, "under": float}} con over + under = 1.0.
    """
    result: dict[float, dict[str, float]] = {}
    for line in lines:
        threshold = math.floor(line)
        over = _poisson_sf(threshold, lam)
        under = 1.0 - over
        result[line] = {"over": over, "under": under}
    return result


# ---------------------------------------------------------------------------
# Funcion de resumen principal (R1, R2, R4)
# ---------------------------------------------------------------------------


def count_summary(
    matches: pd.DataFrame,
    home: str,
    away: str,
    as_of: str,
    stat: str,
    config: CountConfig | None = None,
) -> CountSummary:
    """Calcula el resumen completo del mercado de conteo para un partido (R1, R2, R4).

    Empaqueta tasas con shrinkage, lambdas esperados, O/U total y por equipo, y
    el numero de partidos que sustentan la estimacion (n_matches_home/away).
    Con n bajo la prediccion tira a mu_global por diseno (honestidad, R1).
    Stat no reconocida o columnas ausentes: mu_global=0.0 (degradacion, R1).

    Args:
        matches: Silver DataFrame con home/away_{base} (puede tener NaN).
        home: Codigo FIFA del equipo local.
        away: Codigo FIFA del equipo visitante.
        as_of: Fecha de corte YYYY-MM-DD (anti-fuga, R1).
        stat: Clave de la estadistica ('cards', 'shots', 'sot').
        config: CountConfig con k y lineas custom. None -> CountConfig() default.

    Returns:
        CountSummary con lambdas, O/U total, O/U por equipo y n_matches.
        mu_global=0.0 si no hay datos de la stat disponibles (degradacion).

    Raises:
        KeyError: Si stat no esta en STAT_SPECS (evitable pasando stat valida).
    """
    if config is None:
        config = CountConfig()

    spec = STAT_SPECS[stat]
    lines = tuple(sorted(config.lines if config.lines is not None else spec.lines_default))

    rates, mu_global = count_rates(matches, as_of, stat, k=config.k)

    lam_home, lam_away, lam_total = expected_counts(rates, home, away, mu_global)

    # O/U total usa lambda_total; por equipo usa lambda_home/lambda_away (R2)
    total_ou = tuple(
        CountOULine(line=ln, **ou)
        for ln, ou in sorted(count_over_under(lam_total, lines).items())
    )
    home_ou = tuple(
        CountOULine(line=ln, **ou)
        for ln, ou in sorted(count_over_under(lam_home, lines).items())
    )
    away_ou = tuple(
        CountOULine(line=ln, **ou)
        for ln, ou in sorted(count_over_under(lam_away, lines).items())
    )

    n_home = int(rates.get(home, {}).get("n", 0))
    n_away = int(rates.get(away, {}).get("n", 0))

    return CountSummary(
        home_code=home,
        away_code=away,
        stat=stat,
        label=spec.label,
        noisy_note=spec.noisy_note,
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
