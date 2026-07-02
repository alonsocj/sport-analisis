"""Ingesta pública de resultados internacionales (Feature 7: ingesta_publica, R1–R9).

Descarga el dataset CC0 ``martj42/international_results`` desde una URL pública SIN
credenciales (R1; esta fuente NO usa ``API_FOOTBALL_KEY``), a través de un transporte
inyectable ``url → texto CSV`` (R2), valida el encabezado (R3), persiste el CSV crudo
byte a byte más un sidecar de metadatos en la capa bronze (R4), parsea las filas de forma
tolerante contando descartes por motivo (R5), normaliza tipos por fila válida (R6), expone
el mapa de alias nombre-dataset → código FIFA de las 48 selecciones (R7), y provee el
filtro por las 48 con recorte temporal opcional ``from_date`` (R8, R9).

La descarga real (transporte por defecto con ``requests``) solo ocurre vía la invocación
explícita del CLI ``python -m src.ingestion.public_data`` (R2); importar este módulo no
dispara ninguna conexión de red. Regla STOP de ``CLAUDE.md``: ejecutar el CLI real
requiere aprobación previa del usuario.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .teams import all_teams

# URL pública verificada por el Leader (2026-06-09, HTTP 200). Parametrizable (R1).
DEFAULT_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
)

# Encabezado esperado del CSV: nombres y orden exactos (R3).
EXPECTED_HEADER: tuple[str, ...] = (
    "date",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "tournament",
    "city",
    "country",
    "neutral",
)

DEFAULT_BRONZE_DIR = Path("data") / "bronze"

# transport: url -> texto CSV (UTF-8 decodificado) (R2).
PublicTransport = Callable[[str], str]

# Motivos de descarte del parseo tolerante (R5).
REASON_INVALID_DATE = "fecha_invalida"
REASON_NON_NUMERIC_GOALS = "goles_no_numericos"
REASON_INCOMPLETE_COLUMNS = "columnas_incompletas"


class PublicDownloadError(RuntimeError):
    """Descarga real fallida: status HTTP no exitoso (≠ 2xx) (R2)."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} al descargar {url}")
        self.status_code = status_code
        self.url = url


class PublicSchemaError(RuntimeError):
    """Encabezado del CSV distinto del esperado; incluye esperado y recibido (R3)."""

    def __init__(self, expected: Sequence[str], received: Sequence[str]) -> None:
        super().__init__(
            f"Encabezado inválido. Esperado: {list(expected)}; recibido: {list(received)}"
        )
        self.expected = list(expected)
        self.received = list(received)


@dataclass(frozen=True)
class PublicMatch:
    """Registro normalizado de un partido del dataset público (R6).

    ``date`` ISO ``YYYY-MM-DD``; goles como ``int``; ``neutral`` booleano
    (``TRUE`` → True, ``FALSE`` → False, case-insensitive); el resto ``str``.
    """

    date: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    tournament: str
    city: str
    country: str
    neutral: bool


@dataclass
class IngestReport:
    """Reporte del lote de parseo: totales y descartes por motivo (R5)."""

    n_rows_total: int
    n_valid: int
    n_discarded: int
    discarded_by_reason: dict[str, int]


# Mapa de alias nombre-dataset → código FIFA (R7). VERIFICADO por el Leader (2026-06-09)
# contra el CSV real: los 48 nombres de ``teams.py`` aparecen literales en el dataset
# (p. ej. 'United States' → USA, 'South Korea' → KOR, 'Ivory Coast' → CIV).
# Exportado para que ``feature_store`` lo consuma (home_code/away_code en silver).
DATASET_ALIASES: dict[str, str] = {team.name: team.code for team in all_teams()}


def _default_transport(url: str) -> str:
    """Transporte real con requests (import perezoso: solo si se usa) (R2).

    Decodifica con ``utf-8-sig`` para tolerar un BOM inicial (decisión del Leader, R3).
    Status no exitoso → :class:`PublicDownloadError` y nada se persiste.
    """
    import requests  # noqa: PLC0415  (perezoso a propósito)

    resp = requests.get(url, timeout=60)
    if not 200 <= resp.status_code < 300:
        raise PublicDownloadError(resp.status_code, url)
    return resp.content.decode("utf-8-sig")


def fetch_public_results(transport: PublicTransport, url: str = DEFAULT_URL) -> str:
    """Texto CSV crudo vía el transporte inyectado; sin red real en tests (R1, R2)."""
    return transport(url)


def _strip_bom(csv_text: str) -> str:
    """Tolera un BOM inicial sin considerarlo violación de esquema (R3)."""
    return csv_text[1:] if csv_text.startswith("\ufeff") else csv_text


def validate_header(csv_text: str) -> None:
    """Valida la primera línea (parseada como CSV) contra ``EXPECTED_HEADER`` (R3).

    SI difiere, levanta :class:`PublicSchemaError` con esperado y recibido; la
    validación ocurre ANTES de cualquier escritura bronze (nada se persiste).
    """
    reader = csv.reader(io.StringIO(_strip_bom(csv_text)))
    received = next(reader, [])
    if received != list(EXPECTED_HEADER):
        raise PublicSchemaError(EXPECTED_HEADER, received)


def bronze_public_paths(bronze_dir: Path = DEFAULT_BRONZE_DIR) -> tuple[Path, Path]:
    """Rutas deterministas del snapshot bronze: CSV crudo y sidecar de metadatos (R4)."""
    base = Path(bronze_dir) / "public_results"
    return base / "results.csv", base / "results.meta.json"


def write_bronze_public(
    csv_text: str,
    bronze_dir: Path,
    url: str,
    fetched_at: str,
) -> tuple[Path, Path]:
    """Persiste el CSV crudo tal cual (byte a byte) y el sidecar de metadatos (R4).

    El sidecar incluye ``url``, ``fetched_at`` (timestamp INYECTADO, no reloj interno),
    ``sha256`` del contenido, ``n_rows`` (filas de datos, sin encabezado) y ``header``.
    Cada descarga sobreescribe el snapshot; el ``sha256`` detecta cambios de la fuente.
    """
    csv_path, meta_path = bronze_public_paths(bronze_dir)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    raw = csv_text.encode("utf-8")
    csv_path.write_bytes(raw)

    rows = list(csv.reader(io.StringIO(_strip_bom(csv_text))))
    meta = {
        "url": url,
        "fetched_at": fetched_at,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "n_rows": max(len(rows) - 1, 0),
        "header": list(EXPECTED_HEADER),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, meta_path


def _is_iso_date(value: str) -> bool:
    """True si ``value`` es exactamente ``YYYY-MM-DD`` (R5)."""
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _is_int(value: str) -> bool:
    """True si ``value`` es convertible a int (R5)."""
    try:
        int(value)
    except ValueError:
        return False
    return True


def _row_discard_reason(row: list[str]) -> str | None:
    """Motivo de descarte de una fila, o None si es válida (R5).

    Las filas del calendario del Mundial 2026 (scores ``NA``) se descartan vía
    ``goles_no_numericos`` sin abortar el lote (decisión del Leader).
    """
    if len(row) != len(EXPECTED_HEADER):
        return REASON_INCOMPLETE_COLUMNS
    if not _is_iso_date(row[0]):
        return REASON_INVALID_DATE
    if not (_is_int(row[3]) and _is_int(row[4])):
        return REASON_NON_NUMERIC_GOALS
    return None


def _normalize_row(row: list[str]) -> PublicMatch:
    """Normaliza una fila válida a registro tipado (R6)."""
    return PublicMatch(
        date=row[0],
        home_team=row[1],
        away_team=row[2],
        home_score=int(row[3]),
        away_score=int(row[4]),
        tournament=row[5],
        city=row[6],
        country=row[7],
        neutral=row[8].strip().upper() == "TRUE",
    )


def parse_results(csv_text: str) -> tuple[list[PublicMatch], IngestReport]:
    """Parseo tolerante fila a fila con ``csv`` de stdlib (R5, R6).

    Las filas corruptas (goles no numéricos, fecha inválida, columnas incompletas)
    se descartan y se cuentan por motivo en el :class:`IngestReport`; el lote continúa.
    """
    rows = list(csv.reader(io.StringIO(_strip_bom(csv_text))))
    data_rows = rows[1:]  # sin encabezado

    matches: list[PublicMatch] = []
    discarded_by_reason: dict[str, int] = {}
    for row in data_rows:
        reason = _row_discard_reason(row)
        if reason is not None:
            discarded_by_reason[reason] = discarded_by_reason.get(reason, 0) + 1
            continue
        matches.append(_normalize_row(row))

    report = IngestReport(
        n_rows_total=len(data_rows),
        n_valid=len(matches),
        n_discarded=len(data_rows) - len(matches),
        discarded_by_reason=discarded_by_reason,
    )
    return matches, report


def to_fifa_code(dataset_name: str) -> str | None:
    """Código FIFA de 3 letras para un nombre del dataset (lookup exacto) (R7).

    Nombre desconocido → ``None`` (el filtro lo excluye sin fallar, R8).
    """
    return DATASET_ALIASES.get(dataset_name)


def filter_world_cup_matches(
    matches: Iterable[PublicMatch],
    from_date: str | None = None,
) -> list[PublicMatch]:
    """Vista de consumo: partidos donde participa al menos una de las 48 (R8).

    DONDE se proporcione ``from_date`` (``YYYY-MM-DD``), excluye los partidos con fecha
    estrictamente anterior (comparación lexicográfica válida en ISO) (R9). Sin
    ``from_date`` conserva la historia completa. El recorte es no destructivo: nunca
    altera el CSV crudo persistido en bronze (R9).
    """
    kept = [
        m
        for m in matches
        if to_fifa_code(m.home_team) is not None or to_fifa_code(m.away_team) is not None
    ]
    if from_date is not None:
        kept = [m for m in kept if m.date >= from_date]
    return kept


def ingest_public_results(
    fetched_at: str,
    transport: PublicTransport | None = None,
    url: str = DEFAULT_URL,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
) -> IngestReport:
    """Orquesta la ingesta: fetch → validar encabezado → bronze → parseo (R1–R6).

    ``fetched_at`` se inyecta como argumento (nada de reloj interno en lógica pura).
    Sin transporte inyectado usa el real (descarga efectiva solo vía CLI explícito, R2).
    No requiere ``API_FOOTBALL_KEY`` ni credencial alguna (R1).
    """
    csv_text = fetch_public_results(transport or _default_transport, url)
    validate_header(csv_text)
    write_bronze_public(csv_text, bronze_dir, url, fetched_at)
    _, report = parse_results(csv_text)
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI explícito: única vía de descarga real (R2).

    ``python -m src.ingestion.public_data [--from-date YYYY-MM-DD]``.
    Regla STOP de ``CLAUDE.md``: ejecutar este CLI hace una llamada de red real
    (sin coste de cuota) y requiere aprobación previa del usuario.
    Imprime el :class:`IngestReport` con la convención ``✅ ...`` del repo.
    """
    parser = argparse.ArgumentParser(
        prog="python -m src.ingestion.public_data",
        description="Ingesta pública de resultados internacionales (bronze).",
    )
    parser.add_argument(
        "--from-date",
        default=None,
        help="YYYY-MM-DD; excluye de la vista de consumo los partidos estrictamente anteriores (R9).",
    )
    args = parser.parse_args(argv)

    fetched_at = datetime.now(timezone.utc).isoformat()
    report = ingest_public_results(fetched_at)

    csv_path, meta_path = bronze_public_paths(DEFAULT_BRONZE_DIR)
    matches, _ = parse_results(csv_path.read_text(encoding="utf-8"))
    view = filter_world_cup_matches(matches, from_date=args.from_date)

    print(
        f"✅ Ingesta pública completada: {report.n_rows_total} filas "
        f"({report.n_valid} válidas, {report.n_discarded} descartadas)"
    )
    print(f"✅ Descartes por motivo: {report.discarded_by_reason}")
    print(f"✅ Bronze: {csv_path} + {meta_path}")
    print(
        f"✅ Vista de consumo (48 selecciones, from_date={args.from_date}): "
        f"{len(view)} partidos"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — descarga real solo explícita (R2)
    raise SystemExit(main())
