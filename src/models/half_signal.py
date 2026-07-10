"""src/models/half_signal.py — Feature 32, R4: señal de tendencia por mitad.

Post-proceso del λ de gol que ya produce el modelo de partido completo
(Dixon-Coles + forma-xG + Elo): lo parte en ``λ_1T`` y ``λ_2T`` por equipo usando
*shares* de gol por mitad (ataque propio × defensa del rival por mitad), con
**shrinkage** hacia un prior por muestra chica. **Conserva el total**: solo REPARTE,
no inventa volumen (λ_1T + λ_2T = λ_total).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Prior por defecto del reparto 1T/2T (≈ el fútbol mete algo más de goles en el 2T).
DEFAULT_PRIOR_1T: float = 0.46
# Fuerza de shrinkage para el split 1T/2T (muestra chica en KO).
DEFAULT_K: float = 12.0


def shrink_share(raw: float, n: int, k: float, prior: float) -> float:
    """Encoge un ``share`` observado hacia el ``prior`` (R4).

    ``share_shrunk = (n·raw + k·prior) / (n + k)``. Con ``n`` chico domina el prior;
    con ``n`` grande domina lo observado.

    Args:
        raw: Share observado (0..1).
        n: Nº de partidos que soportan el share.
        k: Fuerza del shrinkage (equivalente a "partidos de prior").
        prior: Share de referencia.

    Returns:
        Share encogido (0..1).
    """
    return (n * raw + k * prior) / (n + k)


def split_lambda(lambda_total: float, share_1t: float) -> tuple[float, float]:
    """Reparte un λ total en (λ_1T, λ_2T) conservando el total (R4).

    Args:
        lambda_total: Goles esperados del partido completo (del modelo bueno).
        share_1t: Fracción del total que va al 1T (0..1).

    Returns:
        Tupla (λ_1T, λ_2T) con λ_1T + λ_2T == lambda_total.
    """
    l1 = lambda_total * share_1t
    return l1, lambda_total - l1


def team_half_shares(silver: pd.DataFrame, team_code: str) -> dict[str, dict[str, float]]:
    """Deriva shares de ataque y defensa por mitad de un equipo desde el silver (R4).

    Args:
        silver: DataFrame con columnas ``team_code, half, gf, ga`` (filas 1T/2T).
        team_code: Equipo objetivo.

    Returns:
        ``{"att": {"1T":s,"2T":s}, "def": {"1T":s,"2T":s}, "n": nº partidos-fila}``.
        ``att[h]`` = fracción de GF del equipo en la mitad ``h``;
        ``def[h]`` = fracción de GA del equipo en la mitad ``h``.
    """
    sub = silver[silver["team_code"] == team_code]
    gf = {h: float(sub[sub["half"] == h]["gf"].sum()) for h in ("1T", "2T")}
    ga = {h: float(sub[sub["half"] == h]["ga"].sum()) for h in ("1T", "2T")}
    gf_tot = gf["1T"] + gf["2T"]
    ga_tot = ga["1T"] + ga["2T"]
    att = {h: (gf[h] / gf_tot if gf_tot else 0.5) for h in ("1T", "2T")}
    dfn = {h: (ga[h] / ga_tot if ga_tot else 0.5) for h in ("1T", "2T")}
    return {"att": att, "def": dfn, "n": int(len(sub))}


def load_half_signal(path: str | Path) -> dict[str, dict[str, dict[str, float]]]:
    """Carga el gold ``half_signal.csv`` a un dict por equipo (R4).

    Args:
        path: Ruta al CSV con columnas team_code, att_1t/att_2t, def_1t/def_2t, …

    Returns:
        ``{code: {"att": {"1T","2T"}, "def": {"1T","2T"}}}`` (vacío si el archivo no existe).
    """
    p = Path(path)
    if not p.is_file():
        return {}
    df = pd.read_csv(p)
    out: dict[str, dict[str, dict[str, float]]] = {}
    for _, r in df.iterrows():
        out[str(r["team_code"])] = {
            "att": {"1T": float(r["att_1t"]), "2T": float(r["att_2t"])},
            "def": {"1T": float(r["def_1t"]), "2T": float(r["def_2t"])},
        }
    return out


def half_lambdas(
    lambda_total: float,
    att_share: dict[str, float],
    opp_def_share: dict[str, float],
) -> tuple[float, float]:
    """Parte λ_total del equipo A ajustando por la defensa del rival B por mitad (R4).

    La tendencia de A a marcar en la mitad ``h`` se pondera por cuánto encaja B en ``h``:
    ``w_h = att_share_A[h] · opp_def_share_B[h]``, normalizado a share_1T y aplicado con
    ``split_lambda`` (conserva el total).

    Args:
        lambda_total: Goles esperados de A en el partido (del modelo completo).
        att_share: Share de ataque por mitad de A (``{"1T":..,"2T":..}``, suma 1).
        opp_def_share: Share defensivo por mitad de B (fracción de goles que B encaja en cada mitad).

    Returns:
        (λ_1T, λ_2T) de A, con λ_1T + λ_2T == lambda_total.
    """
    w1 = att_share["1T"] * opp_def_share["1T"]
    w2 = att_share["2T"] * opp_def_share["2T"]
    total = w1 + w2
    share_1t = (w1 / total) if total else 0.5
    return split_lambda(lambda_total, share_1t)
