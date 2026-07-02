"""Feature 7 — ingesta_publica (R1–R9).

Tests 100% offline y deterministas: transporte falso que devuelve el contenido del
fixture ``tests/fixtures/public_results_sample.csv``; ``fetched_at`` inyectado fijo;
cero red real y cero uso de ``API_FOOTBALL_KEY``.

El fixture contiene 17 filas de datos: 13 válidas y 4 corruptas
(1 fecha inválida, 2 con scores ``NA`` —calendario real del Mundial 2026— y
1 truncada con columnas incompletas).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

from src.ingestion.public_data import (
    DATASET_ALIASES,
    DEFAULT_URL,
    EXPECTED_HEADER,
    IngestReport,
    PublicMatch,
    PublicSchemaError,
    filter_world_cup_matches,
    ingest_public_results,
    parse_results,
    to_fifa_code,
    validate_header,
)
from src.ingestion.teams import all_teams

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = (FIXTURES / "public_results_sample.csv").read_text(encoding="utf-8")

FETCHED_AT = "2026-06-09T12:00:00+00:00"


class FakePublicTransport:
    """Transporte inyectable ``url → texto CSV``; registra llamadas (cero red real)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        return self.text


def test_ingest_works_without_api_football_key(tmp_path, monkeypatch):
    # R1: la ingesta pública funciona SIN API_FOOTBALL_KEY definida (sin credenciales).
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    transport = FakePublicTransport(SAMPLE)

    report = ingest_public_results(
        fetched_at=FETCHED_AT, transport=transport, bronze_dir=tmp_path / "bronze"
    )

    assert isinstance(report, IngestReport)
    assert report.n_rows_total == 17
    assert (tmp_path / "bronze" / "public_results" / "results.csv").is_file()


def test_injected_transport_is_used(tmp_path):
    # R2: el transporte inyectado es el único canal de descarga (URL parametrizable, R1).
    transport = FakePublicTransport(SAMPLE)
    ingest_public_results(FETCHED_AT, transport=transport, bronze_dir=tmp_path / "b1")
    assert transport.calls == [DEFAULT_URL]

    custom = FakePublicTransport(SAMPLE)
    ingest_public_results(
        FETCHED_AT, transport=custom, url="https://example.test/results.csv",
        bronze_dir=tmp_path / "b2",
    )
    assert custom.calls == ["https://example.test/results.csv"]


def test_import_module_triggers_no_download(monkeypatch):
    # R2: importar el módulo no dispara red (import de requests perezoso; cero sockets).
    def _no_net(*_args, **_kwargs):
        raise AssertionError("red real prohibida en tests")

    monkeypatch.setattr(socket, "socket", _no_net)
    monkeypatch.setattr(socket, "create_connection", _no_net)
    monkeypatch.delitem(sys.modules, "requests", raising=False)

    import src.ingestion.public_data as public_data

    # Ejecuta el módulo completo desde cero con la red bloqueada (copia bajo otro
    # nombre para no alterar la identidad del módulo canónico ya importado).
    spec = importlib.util.spec_from_file_location(
        "src.ingestion._public_data_import_check", public_data.__file__
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)  # visible solo durante el test
    spec.loader.exec_module(module)  # si importar descargara algo, _no_net abortaría

    assert "requests" not in sys.modules  # el import de requests es perezoso (R2)
    assert module.DEFAULT_URL == public_data.DEFAULT_URL


def test_header_mismatch_raises_and_persists_nothing(tmp_path):
    # R3: encabezado distinto → PublicSchemaError (esperado vs recibido) y nada en bronze.
    bad = SAMPLE.replace("home_team", "equipo_local", 1)
    bronze_dir = tmp_path / "bronze"

    with pytest.raises(PublicSchemaError) as exc_info:
        ingest_public_results(
            FETCHED_AT, transport=FakePublicTransport(bad), bronze_dir=bronze_dir
        )

    message = str(exc_info.value)
    assert "home_team" in message  # encabezado esperado
    assert "equipo_local" in message  # encabezado recibido
    assert not bronze_dir.exists()  # nada se persistió

    # Decisión del Leader (R3): un BOM inicial se tolera, no es violación de esquema.
    validate_header("\ufeff" + SAMPLE)


def test_bronze_csv_verbatim_and_meta_sidecar(tmp_path):
    # R4: CSV crudo byte a byte + sidecar con url, fetched_at inyectado, sha256, n_rows, header.
    bronze_dir = tmp_path / "bronze"
    ingest_public_results(
        FETCHED_AT, transport=FakePublicTransport(SAMPLE), bronze_dir=bronze_dir
    )

    csv_path = bronze_dir / "public_results" / "results.csv"
    meta_path = bronze_dir / "public_results" / "results.meta.json"
    assert csv_path.read_bytes() == SAMPLE.encode("utf-8")  # byte a byte

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["url"] == DEFAULT_URL
    assert meta["fetched_at"] == FETCHED_AT  # timestamp inyectado, no reloj interno
    assert meta["sha256"] == hashlib.sha256(SAMPLE.encode("utf-8")).hexdigest()
    assert meta["n_rows"] == 17  # filas de datos, sin encabezado
    assert meta["header"] == list(EXPECTED_HEADER)


def test_corrupt_rows_discarded_and_counted():
    # R5: filas corruptas descartadas y contadas por motivo; el lote continúa.
    # Incluye las filas del calendario WC2026 con scores "NA" (decisión del Leader).
    matches, report = parse_results(SAMPLE)

    assert report.n_rows_total == 17
    assert report.n_valid == 13 == len(matches)
    assert report.n_discarded == 4
    assert report.discarded_by_reason == {
        "fecha_invalida": 1,
        "goles_no_numericos": 2,
        "columnas_incompletas": 1,
    }


def test_valid_rows_normalized_types():
    # R6: date ISO str, goles int, neutral bool, resto str.
    matches, _ = parse_results(SAMPLE)

    first = matches[0]
    assert first == PublicMatch(
        date="1950-07-16",
        home_team="Brazil",
        away_team="Uruguay",
        home_score=1,
        away_score=2,
        tournament="FIFA World Cup",
        city="Rio de Janeiro",
        country="Brazil",
        neutral=False,
    )
    assert isinstance(first.date, str)
    assert isinstance(first.home_score, int) and isinstance(first.away_score, int)
    assert isinstance(first.neutral, bool) and first.neutral is False
    assert isinstance(first.tournament, str) and isinstance(first.city, str)
    assert isinstance(first.country, str)

    # neutral TRUE → True.
    arg_fra = next(m for m in matches if m.home_team == "Argentina")
    assert arg_fra.neutral is True


def test_alias_map_covers_48_codes():
    # R7: el mapa cubre exactamente los 48 códigos FIFA de teams.py (ninguno sin alias).
    codes = {t.code for t in all_teams()}
    assert len(codes) == 48
    assert set(DATASET_ALIASES.values()) == codes
    for team in all_teams():
        assert DATASET_ALIASES[team.name] == team.code


def test_to_fifa_code_known_aliases():
    # R7: alias divergentes conocidos resuelven bien; desconocido → None.
    assert to_fifa_code("United States") == "USA"
    assert to_fifa_code("South Korea") == "KOR"
    assert to_fifa_code("Ivory Coast") == "CIV"
    assert to_fifa_code("Curaçao") == "CUW"
    assert to_fifa_code("San Marino") is None


def test_filter_keeps_matches_with_world_cup_team():
    # R8: se conserva el partido si AL MENOS una de las dos selecciones está en las 48.
    matches, _ = parse_results(SAMPLE)
    kept = filter_world_cup_matches(matches)

    assert len(kept) == 11
    pairs = {(m.home_team, m.away_team) for m in kept}
    assert ("San Marino", "Liechtenstein") not in pairs  # ninguna de las 48
    assert ("Gibraltar", "Andorra") not in pairs  # ninguna de las 48
    assert ("United States", "Jamaica") in pairs  # basta con una de las 48 (USA)


def test_from_date_cuts_strictly_older():
    # R9: con from_date se excluyen los partidos estrictamente anteriores (límite inclusivo).
    matches, _ = parse_results(SAMPLE)
    view = filter_world_cup_matches(matches, from_date="2025-11-18")

    assert len(view) == 3
    assert {m.date for m in view} == {"2025-11-18", "2026-03-31"}
    assert all(m.date >= "2025-11-18" for m in view)
    # El recorte es no destructivo: la colección parseada no se altera (bronze intacto).
    assert len(matches) == 13


def test_no_from_date_keeps_full_history():
    # R9: sin from_date se conserva la historia completa (default).
    matches, _ = parse_results(SAMPLE)
    view = filter_world_cup_matches(matches)

    assert len(view) == 11
    assert min(m.date for m in view) == "1950-07-16"  # la historia antigua sigue presente
