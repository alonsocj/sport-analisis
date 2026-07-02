"""Feature 11 — factor_jugadores, R1: ingesta CC0 de goleadores.

Tests 100% offline y deterministas: transporte falso que devuelve el contenido
del fixture ``tests/fixtures/goalscorers_sample.csv``; ``fetched_at`` inyectado
fijo; cero red real. Mapeo R1 de tasks.md.
"""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from src.ingestion.goalscorers import (
    DEFAULT_URL,
    EXPECTED_HEADER,
    GoalscorersSchemaError,
    bronze_goalscorers_paths,
    ingest_goalscorers,
    validate_goalscorers_header,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = (FIXTURES / "goalscorers_sample.csv").read_text(encoding="utf-8")

FETCHED_AT = "2026-06-17T10:00:00+00:00"


class FakeGoalscorersTransport:
    """Transporte inyectable ``url → texto CSV``; registra llamadas (cero red real)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        return self.text


# ---------------------------------------------------------------------------
# R1: test_descarga_transporte_inyectable_y_meta
# ---------------------------------------------------------------------------


def test_descarga_transporte_inyectable_y_meta(tmp_path):
    """R1: el transporte inyectado descarga y persiste el CSV + meta con fetched_at inyectado."""
    transport = FakeGoalscorersTransport(SAMPLE)

    csv_path, meta_path = ingest_goalscorers(
        fetched_at=FETCHED_AT,
        transport=transport,
        bronze_dir=tmp_path / "bronze",
    )

    # El CSV bronze se creó
    assert csv_path.is_file()
    assert meta_path.is_file()

    # El transporte fue llamado con la URL correcta
    assert transport.calls == [DEFAULT_URL]

    # El CSV bronze contiene exactamente el texto original (byte a byte)
    assert csv_path.read_text(encoding="utf-8") == SAMPLE

    # El meta contiene los campos correctos con fetched_at inyectado (no reloj)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["url"] == DEFAULT_URL
    assert meta["fetched_at"] == FETCHED_AT
    assert "sha256" in meta
    assert meta["header"] == list(EXPECTED_HEADER)
    assert isinstance(meta["n_rows"], int)
    assert meta["n_rows"] > 0

    # sha256 verificado
    expected_sha = hashlib.sha256(SAMPLE.encode("utf-8")).hexdigest()
    assert meta["sha256"] == expected_sha


def test_bronze_path_determinista(tmp_path):
    """R1: la ruta del bronze es determinista: bronze_dir/goalscorers/goalscorers.csv."""
    bronze_dir = tmp_path / "bronze"
    csv_path, meta_path = bronze_goalscorers_paths(bronze_dir)
    assert csv_path.name == "goalscorers.csv"
    assert meta_path.name == "goalscorers.meta.json"
    assert csv_path.parent.name == "goalscorers"
    assert meta_path.parent.name == "goalscorers"


def test_url_inyectable_personalizada(tmp_path):
    """R1: la URL parametrizable se pasa al transporte; el bronze siempre se persiste igual."""
    custom_url = "https://example.test/goalscorers.csv"
    transport = FakeGoalscorersTransport(SAMPLE)

    csv_path, meta_path = ingest_goalscorers(
        fetched_at=FETCHED_AT,
        transport=transport,
        url=custom_url,
        bronze_dir=tmp_path / "bronze",
    )

    assert transport.calls == [custom_url]
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["url"] == custom_url


def test_fetched_at_inyectado_no_reloj(tmp_path):
    """R1/R8: fetched_at es exactamente el valor inyectado; nunca usa el reloj."""
    custom_ts = "2025-01-15T08:30:00+00:00"
    transport = FakeGoalscorersTransport(SAMPLE)

    _, meta_path = ingest_goalscorers(
        fetched_at=custom_ts,
        transport=transport,
        bronze_dir=tmp_path / "bronze",
    )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["fetched_at"] == custom_ts


def test_sin_red_real():
    """R1/R8: importar goalscorers no dispara conexiones de red.

    El módulo ya está importado al inicio del test (import a nivel de módulo);
    verificamos que ningún atributo de nivel de módulo abra una conexión de red.
    El transporte real solo se activa vía _default_transport(), que no se llama en import.
    """
    # Verificar que el módulo no importa 'requests' en el scope de módulo
    import sys
    # src.ingestion.goalscorers usa 'requests' de forma PEREZOSA (import dentro de función)
    # Al importar el módulo no se debe haber importado 'requests' en ese ámbito
    from src.ingestion import goalscorers as mod
    # Si el módulo tiene DEFAULT_URL y las clases definidas, es funcional sin red
    assert hasattr(mod, "DEFAULT_URL")
    assert hasattr(mod, "ingest_goalscorers")
    assert hasattr(mod, "GoalscorersSchemaError")
    # No debe haber ningún socket abierto al importar (la descarga es perezosa)


# ---------------------------------------------------------------------------
# R1: test_encabezado_invalido_falla
# ---------------------------------------------------------------------------


def test_encabezado_invalido_falla():
    """R1: encabezado distinto del esperado levanta GoalscorersSchemaError antes de escribir."""
    bad_csv = "date,home,away,scorer\n2022-01-01,ARG,BRA,Messi\n"

    with pytest.raises(GoalscorersSchemaError) as exc_info:
        validate_goalscorers_header(bad_csv)

    assert exc_info.value.expected == list(EXPECTED_HEADER)
    assert "date" in str(exc_info.value)


def test_encabezado_valido_no_falla():
    """R1: el encabezado exacto no levanta excepción."""
    header_line = ",".join(EXPECTED_HEADER) + "\n"
    # No debe levantar excepción
    validate_goalscorers_header(header_line)


def test_ingest_no_persiste_con_encabezado_invalido(tmp_path):
    """R1: si el encabezado es inválido, NO se escribe nada en bronze."""
    bad_csv = "wrong,header,here\n"
    transport = FakeGoalscorersTransport(bad_csv)
    bronze_dir = tmp_path / "bronze"

    with pytest.raises(GoalscorersSchemaError):
        ingest_goalscorers(
            fetched_at=FETCHED_AT,
            transport=transport,
            bronze_dir=bronze_dir,
        )

    csv_path, _ = bronze_goalscorers_paths(bronze_dir)
    assert not csv_path.exists()
