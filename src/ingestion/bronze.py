"""Capa bronze: persistencia cruda de respuestas de la API (R5).

Un archivo JSON por respuesta, en ruta determinista por endpoint + params ordenados:
``data/bronze/<endpoint_dir>/<param_key>.json``. El contenido envuelve el payload crudo
con metadatos (``endpoint``, ``params``, ``fetched_at``). ``fetched_at`` se inyecta para
mantener los tests deterministas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def param_key(params: dict[str, Any]) -> str:
    """Clave determinista a partir de los params (idempotente).

    Ordena por nombre y une como ``k=v`` con ``_``. Vacío → ``"all"``.
    """
    if not params:
        return "all"
    items = sorted((str(k), str(v)) for k, v in params.items())
    return "_".join(f"{k}={v}" for k, v in items)


def bronze_path(bronze_dir: Path, endpoint: str, params: dict[str, Any]) -> Path:
    """Ruta determinista del archivo bronze para (endpoint, params)."""
    endpoint_dir = endpoint.strip("/").replace("/", "_")
    return Path(bronze_dir) / endpoint_dir / f"{param_key(params)}.json"


def write_bronze(
    bronze_dir: Path,
    endpoint: str,
    params: dict[str, Any],
    payload: Any,
    fetched_at: str,
) -> Path:
    """Escribe el payload crudo envuelto con metadatos. Devuelve la ruta escrita."""
    path = bronze_path(bronze_dir, endpoint, params)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "endpoint": endpoint,
        "params": params,
        "fetched_at": fetched_at,
        "payload": payload,
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_bronze(bronze_dir: Path, endpoint: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Lee un registro bronze si existe; si no, None."""
    path = bronze_path(bronze_dir, endpoint, params)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
