"""R8–R11 — medias móviles de los últimos 15 partidos (offline, DataFrames en memoria)."""

from __future__ import annotations

import pandas as pd

from src.features.rolling import FEATURE_COLUMNS, compute_rolling_features
from src.features.silver import SILVER_COLUMNS, STAT_COLUMNS


def _match(date, home, away, hg, ag, **stats):
    """Fila silver mínima y determinista; stats nulas salvo override explícito."""
    row = {
        "match_id": f"{date}|{home}|{away}",
        "date": date,
        "home_code": home,
        "away_code": away,
        "home_team": home,
        "away_team": away,
        "home_goals": hg,
        "away_goals": ag,
        "tournament": "Friendly",
        "neutral": False,
        "source": "public_csv",
    }
    row.update({c: None for c in STAT_COLUMNS})
    row.update(stats)
    return row


def _silver(rows):
    df = pd.DataFrame(rows, columns=list(SILVER_COLUMNS))
    for col in STAT_COLUMNS:
        df[col] = df[col].astype(float)
    return df


def test_media_movil_15_por_metrica():
    # R8: media de las últimas hasta 15 observaciones NO nulas, por equipo y métrica.
    rows = []
    # 16 partidos previos de ARG: el más antiguo (gf=100) debe quedar FUERA de la ventana.
    rows.append(_match("2025-01-01", "ARG", "BRA", 100, 0))
    for day in range(2, 17):  # 2025-01-02 .. 2025-01-16, gf=1 ga=0
        rows.append(_match(f"2025-01-{day:02d}", "ARG", "BRA", 1, 0))
    # Posesión solo en 3 partidos: la media usa SOLO las observaciones no nulas.
    rows[-3].update({"home_possession": 60.0})
    rows[-2].update({"home_possession": 50.0})
    rows[-1].update({"home_possession": 40.0})

    feats = compute_rolling_features(_silver(rows), ["ARG"], "2025-02-01")
    arg = feats.iloc[0]

    assert arg["matches_count"] == 15  # ventana de 15 sobre 16 previos
    assert arg["gf_ma15"] == 1.0  # el gf=100 (16º hacia atrás) queda fuera
    assert arg["ga_ma15"] == 0.0
    assert arg["possession_ma15"] == 50.0  # media de las 3 obs. no nulas
    assert pd.isna(arg["corners_for_ma15"])  # métrica sin ninguna observación


def test_excluye_partido_actual_y_futuros():
    # R9: anti-leakage — date >= as_of_date queda fuera (incluido el propio partido).
    rows = [
        _match("2025-01-01", "ARG", "BRA", 2, 0),  # previo: cuenta
        _match("2025-01-10", "ARG", "BRA", 4, 0),  # el partido a predecir: fuera
        _match("2025-01-15", "ARG", "BRA", 6, 0),  # futuro: fuera
    ]
    feats = compute_rolling_features(_silver(rows), ["ARG"], "2025-01-10")
    arg = feats.iloc[0]

    assert arg["matches_count"] == 1
    assert arg["gf_ma15"] == 2.0  # solo el partido estrictamente anterior


def test_ventana_corta_matches_count():
    # R10: con <15 previos usa los disponibles y reporta matches_count.
    rows = [
        _match("2025-01-01", "ARG", "BRA", 0, 1),
        _match("2025-01-02", "ARG", "BRA", 1, 1),
        _match("2025-01-03", "ARG", "BRA", 2, 1),
    ]
    feats = compute_rolling_features(_silver(rows), ["ARG"], "2025-06-01")
    arg = feats.iloc[0]

    assert arg["matches_count"] == 3
    assert arg["gf_ma15"] == 1.0  # media de 0, 1, 2
    assert arg["ga_ma15"] == 1.0


def test_cero_partidos_features_nulas():
    # R10: 0 partidos previos → features nulas y matches_count = 0, sin fallar.
    rows = [_match("2025-01-01", "ARG", "BRA", 1, 0)]
    feats = compute_rolling_features(_silver(rows), ["JPN"], "2025-06-01")
    jpn = feats.iloc[0]

    assert jpn["matches_count"] == 0
    assert jpn[list(FEATURE_COLUMNS)].isna().all()


def test_stats_nulas_con_solo_fuente_publica():
    # R11: solo observaciones sin stats (fuente pública) → stats null,
    # pero gf_ma15/ga_ma15 calculadas.
    rows = [
        _match("2025-01-01", "MEX", "USA", 2, 1),
        _match("2025-01-05", "CAN", "MEX", 0, 3),
    ]
    feats = compute_rolling_features(_silver(rows), ["MEX"], "2025-06-01")
    mex = feats.iloc[0]

    assert mex["matches_count"] == 2
    assert mex["gf_ma15"] == 2.5  # (2 + 3) / 2 — incluye perspectiva visitante
    assert mex["ga_ma15"] == 0.5  # (1 + 0) / 2
    for col in (
        "corners_for_ma15",
        "corners_against_ma15",
        "cards_ma15",
        "shots_ma15",
        "shots_on_target_ma15",
        "possession_ma15",
    ):
        assert pd.isna(mex[col])
