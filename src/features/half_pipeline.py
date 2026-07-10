"""src/features/half_pipeline.py — Feature 32 (integración): construir la señal gold.

Convierte fuentes crudas (eventos fotmob per-mitad ya parseados + goalscorers.csv con
minutos) en la tabla gold ``half_signal`` por equipo: shares de ataque/defensa por mitad
(encogidos hacia el prior) + goles y xG por mitad + nº de partidos.

Reutiliza ``team_half_shares``/``shrink_share`` (probados) y ``build_silver_por_mitad``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.models.half_signal import (
    DEFAULT_K,
    DEFAULT_PRIOR_1T,
    shrink_share,
    team_half_shares,
)


def matches_from_goalscorers(
    goalscorers: pd.DataFrame, code_map: dict[str, str]
) -> list[dict[str, Any]]:
    """Convierte filas de ``goalscorers.csv`` en 'matches' para el silver por-mitad.

    Cada partido (date, home_team, away_team) agrupa sus goles con minuto; ``is_home``
    se deriva de ``team == home_team``. Sin cobertura per-mitad → ``periods={}``.
    Partidos con algún equipo sin código FIFA se descartan.

    Args:
        goalscorers: DataFrame con columnas date, home_team, away_team, team, minute, own_goal.
        code_map: Nombre de equipo → código FIFA.

    Returns:
        Lista de dicts con match_id/date/home_code/away_code/periods/goals.
    """
    out: list[dict[str, Any]] = []
    for (date, home, away), grp in goalscorers.groupby(
        ["date", "home_team", "away_team"], sort=True
    ):
        hc, ac = code_map.get(home), code_map.get(away)
        if hc is None or ac is None:
            continue
        goals: list[dict[str, Any]] = []
        for _, r in grp.iterrows():
            if pd.isna(r["minute"]):
                continue
            goals.append(
                {
                    "minute": int(r["minute"]),
                    "is_home": bool(r["team"] == home),
                    "own_goal": bool(r.get("own_goal", False)),
                }
            )
        out.append(
            {
                "match_id": f"gs-{date}-{hc}-{ac}",
                "date": str(date),
                "home_code": hc,
                "away_code": ac,
                "periods": {},
                "goals": goals,
            }
        )
    return out


def build_half_signal(
    silver: pd.DataFrame,
    teams: list[str] | None = None,
    k: float = DEFAULT_K,
    prior: float = DEFAULT_PRIOR_1T,
) -> pd.DataFrame:
    """Agrega el silver por-mitad a la señal gold por equipo (R4).

    Args:
        silver: DataFrame silver por-mitad (filas equipo×mitad).
        teams: Equipos a incluir (default: todos los presentes).
        k: Fuerza de shrinkage de los shares.
        prior: Prior del share de 1T (defensa y ataque, simétrico).

    Returns:
        DataFrame por equipo con shares shrunk (att/def 1T/2T), goles y xG por mitad, y n.
    """
    teams = teams or sorted(silver["team_code"].unique())
    rows: list[dict[str, Any]] = []
    for t in teams:
        sub = silver[silver["team_code"] == t]
        n = int(sub["match_id"].nunique())
        sh = team_half_shares(sub, t)
        att1 = shrink_share(sh["att"]["1T"], n, k, prior)
        def1 = shrink_share(sh["def"]["1T"], n, k, prior)
        cov = sub[sub["cover_xg"] == True]  # noqa: E712

        def _mean(col: str, half: str) -> float | None:
            v = cov[cov["half"] == half][col].dropna()
            return float(v.mean()) if len(v) else None

        rows.append(
            {
                "team_code": t,
                "n": n,
                "att_1t": att1,
                "att_2t": 1.0 - att1,
                "def_1t": def1,
                "def_2t": 1.0 - def1,
                "gf_1t": int(sub[sub["half"] == "1T"]["gf"].sum()),
                "gf_2t": int(sub[sub["half"] == "2T"]["gf"].sum()),
                "ga_1t": int(sub[sub["half"] == "1T"]["ga"].sum()),
                "ga_2t": int(sub[sub["half"] == "2T"]["ga"].sum()),
                "xg_for_1t": _mean("xg_for", "1T"),
                "xg_for_2t": _mean("xg_for", "2T"),
                "xg_ag_1t": _mean("xg_against", "1T"),
                "xg_ag_2t": _mean("xg_against", "2T"),
            }
        )
    return pd.DataFrame(rows)
