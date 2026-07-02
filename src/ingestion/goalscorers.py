"""Ingesta CC0 de goleadores internacionales (Feature 11: factor_jugadores, R1).

Descarga ``goalscorers.csv`` del repo CC0 martj42 desde una URL pública SIN
credenciales, a través de un transporte INYECTABLE ``url → texto CSV`` (misma
convención que ``src/ingestion/public_data.py``), valida el encabezado EXACTO
``[date, home_team, away_team, team, scorer, minute, own_goal, penalty]`` y persiste
el CSV crudo byte a byte más un sidecar de metadatos en la capa bronze.

La descarga real (transporte por defecto con ``requests``) solo ocurre vía invocación
explícita del CLI ``ingest-goalscorers`` (R1); importar este módulo no dispara ninguna
conexión de red. Regla STOP de ``CLAUDE.md``: ejecutar el CLI real requiere aprobación
previa del usuario.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Callable, Sequence

# URL pública verificada por el Leader (2026-06-17, HTTP 200). Parametrizable (R1).
DEFAULT_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/master/goalscorers.csv"
)

# Encabezado esperado del CSV: nombres y orden exactos (R1).
EXPECTED_HEADER: tuple[str, ...] = (
    "date",
    "home_team",
    "away_team",
    "team",
    "scorer",
    "minute",
    "own_goal",
    "penalty",
)

DEFAULT_BRONZE_DIR = Path("data") / "bronze"

# transport: url -> texto CSV (UTF-8 decodificado) (R1).
GoalscorersTransport = Callable[[str], str]


class GoalscorersDownloadError(RuntimeError):
    """Descarga real fallida: status HTTP no exitoso (≠ 2xx) (R1)."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} al descargar {url}")
        self.status_code = status_code
        self.url = url


class GoalscorersSchemaError(RuntimeError):
    """Encabezado del CSV distinto del esperado; incluye esperado y recibido (R1)."""

    def __init__(self, expected: Sequence[str], received: Sequence[str]) -> None:
        super().__init__(
            f"Encabezado inválido. Esperado: {list(expected)}; recibido: {list(received)}"
        )
        self.expected = list(expected)
        self.received = list(received)


def _default_transport(url: str) -> str:
    """Transporte real con requests (import perezoso: solo si se usa) (R1).

    Decodifica con ``utf-8-sig`` para tolerar un BOM inicial.
    Status no exitoso → :class:`GoalscorersDownloadError` y nada se persiste.
    """
    import requests  # noqa: PLC0415  (perezoso a propósito)

    resp = requests.get(url, timeout=60)
    if not 200 <= resp.status_code < 300:
        raise GoalscorersDownloadError(resp.status_code, url)
    return resp.content.decode("utf-8-sig")


def fetch_goalscorers(transport: GoalscorersTransport, url: str = DEFAULT_URL) -> str:
    """Texto CSV crudo vía el transporte inyectado; sin red real en tests (R1)."""
    return transport(url)


def _strip_bom(csv_text: str) -> str:
    """Tolera un BOM inicial sin considerarlo violación de esquema (R1)."""
    return csv_text[1:] if csv_text.startswith("﻿") else csv_text


def validate_goalscorers_header(csv_text: str) -> None:
    """Valida la primera línea (parseada como CSV) contra ``EXPECTED_HEADER`` (R1).

    SI difiere, levanta :class:`GoalscorersSchemaError` con esperado y recibido;
    la validación ocurre ANTES de cualquier escritura bronze (nada se persiste).
    """
    reader = csv.reader(io.StringIO(_strip_bom(csv_text)))
    received = next(reader, [])
    if received != list(EXPECTED_HEADER):
        raise GoalscorersSchemaError(EXPECTED_HEADER, received)


def bronze_goalscorers_paths(
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
) -> tuple[Path, Path]:
    """Rutas deterministas del snapshot bronze: CSV crudo y sidecar de metadatos (R1)."""
    base = Path(bronze_dir) / "goalscorers"
    return base / "goalscorers.csv", base / "goalscorers.meta.json"


def write_bronze_goalscorers(
    csv_text: str,
    bronze_dir: Path,
    url: str,
    fetched_at: str,
) -> tuple[Path, Path]:
    """Persiste el CSV crudo tal cual (byte a byte) y el sidecar de metadatos (R1).

    El sidecar incluye ``url``, ``fetched_at`` (timestamp INYECTADO, no reloj interno),
    ``sha256`` del contenido, ``n_rows`` (filas de datos, sin encabezado) y ``header``.
    Cada descarga sobreescribe el snapshot; el ``sha256`` detecta cambios de la fuente.
    """
    csv_path, meta_path = bronze_goalscorers_paths(bronze_dir)
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


def ingest_goalscorers(
    fetched_at: str,
    transport: GoalscorersTransport | None = None,
    url: str = DEFAULT_URL,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
) -> tuple[Path, Path]:
    """Orquesta la ingesta: fetch → validar encabezado → bronze (R1).

    ``fetched_at`` se inyecta como argumento (nada de reloj interno en lógica pura).
    Sin transporte inyectado usa el real (descarga efectiva solo vía CLI explícito, R1).
    No requiere ``API_FOOTBALL_KEY`` ni credencial alguna (R1).

    Returns:
        Tuple of (csv_path, meta_path) para el bronze persistido.
    """
    csv_text = fetch_goalscorers(transport or _default_transport, url)
    validate_goalscorers_header(csv_text)
    return write_bronze_goalscorers(csv_text, bronze_dir, url, fetched_at)
