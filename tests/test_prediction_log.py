"""Feature 10 — registro_y_evaluacion: tests de prediction_log (R1–R5).

100 % offline y deterministas: se usa un silver sintético en tmp_path y se
llama a ``log_predictions`` con entrenamiento REAL (sin mocks del modelo), ya
que el silver sintético es pequeño pero válido para fit_dixon_coles. El
timestamp siempre se inyecta como argumento (R2). Cero red.

Trazabilidad:
    R1 → test_esquema_columnas_y_probs_suman_uno
    R2 → test_timestamp_inyectado_sin_reloj
    R3 → test_anti_fuga_as_of_mutar_futuro_no_cambia
    R4 → test_upsert_sin_duplicados_y_orden_determinista
    R5 → test_objetivos_pendientes_y_skipped_equipo_fuera
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.eval.prediction_log import (
    LOG_COLUMNS,
    MODEL_VERSION,
    fixtures_from_csv,
    fixtures_from_schedule,
    log_predictions,
)

# ---------------------------------------------------------------------------
# Constantes de test
# ---------------------------------------------------------------------------

AS_OF = "2026-06-11"
TIMESTAMP = "2026-06-11T10:00:00Z"

# Equipos del silver sintético (todos conocidos por el modelo después del fit)
TEAMS = ["ARG", "BRA", "FRA", "GER", "MEX", "USA", "JPN", "KOR", "ESP", "POR"]


# ---------------------------------------------------------------------------
# Helpers: silver sintético
# ---------------------------------------------------------------------------


def _make_silver_csv(tmp_path: Path, n_matches_per_team: int = 10) -> Path:
    """Silver sintético con suficientes partidos para entrenar Dixon-Coles.

    Genera una ronda todos-contra-todos con marcadores fijos y fechas
    estrictamente anteriores a AS_OF (2026-06-11). El neutral es siempre False.
    """
    silver_dir = tmp_path / "data" / "silver"
    silver_dir.mkdir(parents=True, exist_ok=True)
    path = silver_dir / "matches.csv"

    rows = []
    date_counter = 1
    for i, home in enumerate(TEAMS):
        for j, away in enumerate(TEAMS):
            if i >= j:
                continue
            # fecha < AS_OF: 2026-05-XX para garantizar no-fuga
            date_str = f"2026-05-{date_counter:02d}"
            date_counter = (date_counter % 28) + 1
            match_id = f"synth_{home}_{away}"
            rows.append({
                "match_id": match_id,
                "date": date_str,
                "home_code": home,
                "away_code": away,
                "home_goals": 1,
                "away_goals": 1,
                "neutral": False,
            })

    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    return path


def _make_fixtures(teams_subset: list[str] = None) -> list[dict[str, Any]]:
    """Lista de fixtures con match_id estable para usar en tests."""
    teams = teams_subset or TEAMS[:4]
    fixtures = []
    for i in range(0, len(teams) - 1, 2):
        home = teams[i]
        away = teams[i + 1]
        fixtures.append({
            "date": "2026-06-15",
            "match_id": f"wc_{home}_{away}",
            "home_code": home,
            "away_code": away,
            "neutral": False,
        })
    return fixtures


# ---------------------------------------------------------------------------
# R1 — test_esquema_columnas_y_probs_suman_uno
# ---------------------------------------------------------------------------


def test_esquema_columnas_y_probs_suman_uno(tmp_path):
    """R1: columnas del log en orden fijo; p_home+p_draw+p_away = 1 (tol 1e-9)."""
    silver_path = _make_silver_csv(tmp_path)
    log_path = tmp_path / "data" / "predictions" / "log.csv"
    fixtures = _make_fixtures(["ARG", "BRA"])

    result = log_predictions(
        as_of_date=AS_OF,
        created_at=TIMESTAMP,
        fixtures=fixtures,
        include_markets=False,
        silver_path=silver_path,
        log_path=log_path,
    )

    assert result["n_logged"] == 1
    assert result["n_skipped"] == 0

    df = pd.read_csv(log_path, dtype=str)

    # Columnas en orden fijo del contrato (R1)
    assert list(df.columns) == list(LOG_COLUMNS), (
        f"Columnas del log no coinciden con el contrato.\n"
        f"Esperadas: {list(LOG_COLUMNS)}\n"
        f"Obtenidas: {list(df.columns)}"
    )

    # p_home + p_draw + p_away = 1 (R1)
    for _, row in df.iterrows():
        total = float(row["p_home"]) + float(row["p_draw"]) + float(row["p_away"])
        assert abs(total - 1.0) < 1e-9, (
            f"Probabilidades no suman 1: {total} para match_id={row['match_id']}"
        )

    # Columnas de mercado vacías sin --markets (R1)
    # pandas lee celdas vacías como NaN con dtype=str; ambas formas son "ausente"
    import math as _math
    p_over_val = row["p_over25"]
    p_btts_val = row["p_btts"]
    assert p_over_val == "" or (isinstance(p_over_val, float) and _math.isnan(p_over_val)), (
        f"p_over25 debe estar vacía/NaN: {p_over_val!r}"
    )
    assert p_btts_val == "" or (isinstance(p_btts_val, float) and _math.isnan(p_btts_val)), (
        f"p_btts debe estar vacía/NaN: {p_btts_val!r}"
    )

    # model_version = dc-v1 (R1)
    assert row["model_version"] == MODEL_VERSION


def test_esquema_columnas_con_mercados(tmp_path):
    """R1: columnas p_over25 y p_btts no vacías cuando --markets activo."""
    silver_path = _make_silver_csv(tmp_path)
    log_path = tmp_path / "data" / "predictions" / "log.csv"
    fixtures = _make_fixtures(["ARG", "BRA"])

    log_predictions(
        as_of_date=AS_OF,
        created_at=TIMESTAMP,
        fixtures=fixtures,
        include_markets=True,
        silver_path=silver_path,
        log_path=log_path,
    )

    df = pd.read_csv(log_path, dtype=str)
    row = df.iloc[0]
    assert row["p_over25"] != "", "p_over25 debe tener valor con --markets"
    assert row["p_btts"] != "", "p_btts debe tener valor con --markets"

    p_over = float(row["p_over25"])
    p_btts = float(row["p_btts"])
    assert 0.0 <= p_over <= 1.0
    assert 0.0 <= p_btts <= 1.0


# ---------------------------------------------------------------------------
# R2 — test_timestamp_inyectado_sin_reloj
# ---------------------------------------------------------------------------


def test_timestamp_inyectado_sin_reloj(tmp_path):
    """R2: dos llamadas con mismo timestamp producen mismo created_at; sin reloj."""
    # Verificar que el código fuente NO usa datetime.now()
    source_path = Path(__file__).resolve().parent.parent / "src" / "eval" / "prediction_log.py"
    source = source_path.read_text(encoding="utf-8")
    assert "datetime.now()" not in source, (
        "prediction_log.py no debe usar datetime.now() (R2)"
    )
    assert "datetime.utcnow()" not in source, (
        "prediction_log.py no debe usar datetime.utcnow() (R2)"
    )

    silver_path = _make_silver_csv(tmp_path)
    fixtures = _make_fixtures(["ARG", "BRA"])

    ts1 = "2026-06-11T08:00:00Z"
    ts2 = "2026-06-11T08:00:00Z"  # mismo timestamp

    log_path1 = tmp_path / "data" / "log1.csv"
    log_path2 = tmp_path / "data" / "log2.csv"

    log_predictions(
        as_of_date=AS_OF,
        created_at=ts1,
        fixtures=fixtures,
        silver_path=silver_path,
        log_path=log_path1,
    )
    log_predictions(
        as_of_date=AS_OF,
        created_at=ts2,
        fixtures=fixtures,
        silver_path=silver_path,
        log_path=log_path2,
    )

    df1 = pd.read_csv(log_path1, dtype=str)
    df2 = pd.read_csv(log_path2, dtype=str)

    assert df1["created_at"].iloc[0] == ts1, "created_at no coincide con ts1"
    assert df2["created_at"].iloc[0] == ts2, "created_at no coincide con ts2"
    assert df1["created_at"].iloc[0] == df2["created_at"].iloc[0], (
        "Mismo timestamp → mismo created_at (R2)"
    )


def test_timestamp_invalido_lanza_error(tmp_path):
    """R2: timestamp con formato inválido lanza ValueError."""
    silver_path = _make_silver_csv(tmp_path)
    log_path = tmp_path / "data" / "log.csv"
    fixtures = _make_fixtures(["ARG", "BRA"])

    with pytest.raises(ValueError, match="ISO-8601"):
        log_predictions(
            as_of_date=AS_OF,
            created_at="NO-ES-FECHA",
            fixtures=fixtures,
            silver_path=silver_path,
            log_path=log_path,
        )


# ---------------------------------------------------------------------------
# R3 — test_anti_fuga_as_of_mutar_futuro_no_cambia
# ---------------------------------------------------------------------------


def test_anti_fuga_as_of_mutar_futuro_no_cambia(tmp_path):
    """R3: mutar/eliminar resultados con fecha >= as_of_date NO cambia las predicciones.

    Se generan predicciones con un silver base. Luego se añaden filas con fecha
    >= AS_OF (simulando resultados futuros/del torneo) y se regeneran. Las
    probabilidades deben ser idénticas (tolerancia 1e-12).
    """
    silver_path = _make_silver_csv(tmp_path)
    fixtures = _make_fixtures(["ARG", "BRA"])

    log_path_base = tmp_path / "data" / "log_base.csv"
    log_path_mutado = tmp_path / "data" / "log_mutado.csv"

    # Primera generación (silver sin resultados futuros)
    log_predictions(
        as_of_date=AS_OF,
        created_at=TIMESTAMP,
        fixtures=fixtures,
        silver_path=silver_path,
        log_path=log_path_base,
    )
    df_base = pd.read_csv(log_path_base)

    # Añadir filas con fecha >= AS_OF al silver (fuga potencial)
    df_silver = pd.read_csv(silver_path)
    fuga_rows = []
    for i, (h, a) in enumerate([("ARG", "BRA"), ("FRA", "GER")]):
        fuga_rows.append({
            "match_id": f"fuga_{i}",
            "date": f"2026-06-{11 + i:02d}",  # >= AS_OF
            "home_code": h,
            "away_code": a,
            "home_goals": 5,  # marcadores extremos que cambiarían el modelo
            "away_goals": 0,
            "neutral": False,
        })
    df_silver_mutado = pd.concat([df_silver, pd.DataFrame(fuga_rows)], ignore_index=True)
    silver_mutado_path = tmp_path / "silver_mutado.csv"
    df_silver_mutado.to_csv(silver_mutado_path, index=False)

    # Segunda generación con silver mutado
    log_predictions(
        as_of_date=AS_OF,
        created_at=TIMESTAMP,
        fixtures=fixtures,
        silver_path=silver_mutado_path,
        log_path=log_path_mutado,
    )
    df_mutado = pd.read_csv(log_path_mutado)

    # Las predicciones deben ser idénticas (anti-fuga: fecha < AS_OF)
    for col in ["p_home", "p_draw", "p_away", "lambda_home", "lambda_away"]:
        for i in range(len(df_base)):
            diff = abs(float(df_base[col].iloc[i]) - float(df_mutado[col].iloc[i]))
            assert diff < 1e-12, (
                f"Anti-fuga violada: columna {col}, fila {i}, diferencia={diff} "
                f"(R3)"
            )


# ---------------------------------------------------------------------------
# R4 — test_upsert_sin_duplicados_y_orden_determinista
# ---------------------------------------------------------------------------


def test_upsert_sin_duplicados_y_orden_determinista(tmp_path):
    """R4: upsert por clave sin duplicados; archivo ordenado deterministamente."""
    silver_path = _make_silver_csv(tmp_path)
    log_path = tmp_path / "data" / "predictions" / "log.csv"

    # Fixtures con fechas distintas para verificar el orden
    fixtures_batch1 = [
        {"date": "2026-06-20", "match_id": "wc_ARG_BRA", "home_code": "ARG", "away_code": "BRA", "neutral": False},
        {"date": "2026-06-18", "match_id": "wc_FRA_GER", "home_code": "FRA", "away_code": "GER", "neutral": False},
    ]
    fixtures_batch2 = [
        # misma clave que el primero → debe sobrescribir
        {"date": "2026-06-20", "match_id": "wc_ARG_BRA", "home_code": "ARG", "away_code": "BRA", "neutral": False},
        # fixture nuevo
        {"date": "2026-06-19", "match_id": "wc_ESP_POR", "home_code": "ESP", "away_code": "POR", "neutral": False},
    ]

    # Primera inserción
    log_predictions(
        as_of_date=AS_OF,
        created_at="2026-06-11T08:00:00Z",
        fixtures=fixtures_batch1,
        silver_path=silver_path,
        log_path=log_path,
    )

    # Segunda inserción con upsert
    log_predictions(
        as_of_date=AS_OF,
        created_at="2026-06-11T09:00:00Z",  # timestamp diferente
        fixtures=fixtures_batch2,
        silver_path=silver_path,
        log_path=log_path,
    )

    df = pd.read_csv(log_path, dtype=str)

    # Sin duplicados por clave (R4)
    key_combos = list(zip(df["match_id"], df["as_of_date"], df["model_version"]))
    assert len(key_combos) == len(set(key_combos)), (
        "Duplicados en el log por clave (match_id, as_of_date, model_version) (R4)"
    )

    # 3 partidos únicos: wc_ARG_BRA (upserted), wc_FRA_GER, wc_ESP_POR
    assert len(df) == 3, f"Se esperaban 3 filas, hay {len(df)}"

    # La fila de ARG_BRA fue actualizada (timestamp más reciente)
    row_arg_bra = df[df["match_id"] == "wc_ARG_BRA"].iloc[0]
    assert row_arg_bra["created_at"] == "2026-06-11T09:00:00Z", (
        "Upsert: la fila debe actualizarse con el nuevo timestamp (R4)"
    )

    # Orden determinista por (match_date, match_id, as_of_date) (R4)
    expected_order = ["wc_FRA_GER", "wc_ESP_POR", "wc_ARG_BRA"]
    actual_order = list(df["match_id"])
    assert actual_order == expected_order, (
        f"Orden del log no es determinista.\nEsperado: {expected_order}\nObtenido: {actual_order}"
    )


# ---------------------------------------------------------------------------
# R5 — test_objetivos_pendientes_y_skipped_equipo_fuera
# ---------------------------------------------------------------------------


def test_objetivos_pendientes_y_skipped_equipo_fuera(tmp_path):
    """R5: fixture con equipo fuera del recorte → skipped sin abortar el resto."""
    silver_path = _make_silver_csv(tmp_path)
    log_path = tmp_path / "data" / "predictions" / "log.csv"

    # "XYZ" no está en el silver → fuera del recorte del modelo
    fixtures = [
        {"date": "2026-06-15", "match_id": "wc_ARG_BRA", "home_code": "ARG", "away_code": "BRA", "neutral": False},
        {"date": "2026-06-15", "match_id": "wc_XYZ_ARG", "home_code": "XYZ", "away_code": "ARG", "neutral": False},
    ]

    result = log_predictions(
        as_of_date=AS_OF,
        created_at=TIMESTAMP,
        fixtures=fixtures,
        silver_path=silver_path,
        log_path=log_path,
    )

    # El fixture válido se loguea; el de XYZ se skipea
    assert result["n_logged"] == 1, f"Se esperaba 1 logged, hay {result['n_logged']}"
    assert result["n_skipped"] == 1, f"Se esperaba 1 skipped, hay {result['n_skipped']}"

    # El motivo del skip es correcto (R5)
    assert result["skipped"][0]["reason"] == "equipo_fuera_de_recorte", (
        f"Motivo de skip incorrecto: {result['skipped'][0]['reason']!r}"
    )
    assert result["skipped"][0]["match_id"] == "wc_XYZ_ARG"

    # El log solo contiene el fixture válido
    df = pd.read_csv(log_path, dtype=str)
    assert len(df) == 1
    assert df.iloc[0]["match_id"] == "wc_ARG_BRA"


def test_fixtures_from_csv(tmp_path):
    """R5: fixtures_from_csv carga correctamente un CSV de fixtures."""
    csv_path = tmp_path / "fixtures.csv"
    csv_path.write_text(
        "date,match_id,home_code,away_code,neutral\n"
        "2026-06-15,m1,ARG,BRA,False\n"
        "2026-06-16,m2,FRA,GER,True\n",
        encoding="utf-8",
    )
    fixtures = fixtures_from_csv(csv_path)
    assert len(fixtures) == 2
    assert fixtures[0]["match_id"] == "m1"
    assert fixtures[1]["neutral"] is True


def test_fixtures_from_schedule(tmp_path):
    """R5: fixtures_from_schedule filtra partidos WC2026 pendientes."""
    bronze_path = tmp_path / "results.csv"
    bronze_path.write_text(
        "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
        "2026-06-11,Mexico,United States,,,FIFA World Cup,,,False\n"
        "2026-06-12,Canada,Germany,0,4,FIFA World Cup,,,False\n"
        "2026-06-13,France,Brazil,,,Copa America,,,False\n",
        encoding="utf-8",
    )
    fixtures = fixtures_from_schedule(bronze_path)
    # Solo el primer partido: WC2026 sin score numérico
    assert len(fixtures) == 1
    assert fixtures[0]["date"] == "2026-06-11"
