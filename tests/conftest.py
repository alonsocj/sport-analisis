"""Utilidades de test: transporte HTTP falso y carga de fixtures (sin red real)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# Hacer importable el paquete src/
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@dataclass
class FakeResponse:
    status_code: int
    _json: Any

    def json(self) -> Any:
        return self._json


class FakeTransport:
    """Transporte inyectable. Programado con una cola de respuestas o un router por endpoint.

    - ``queue``: lista de FakeResponse devueltas en orden (para probar reintentos).
    - ``router``: dict endpoint-substring → FakeResponse.
    Registra cada llamada en ``self.calls``.
    """

    def __init__(self, queue: list[FakeResponse] | None = None, router: dict[str, FakeResponse] | None = None):
        self.queue = list(queue or [])
        self.router = router or {}
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], params: dict[str, Any]) -> FakeResponse:
        self.calls.append({"method": method, "url": url, "headers": headers, "params": params})
        if self.queue:
            return self.queue.pop(0)
        for key, resp in self.router.items():
            if key in url:
                return resp
        raise AssertionError(f"FakeTransport sin respuesta para {url}")


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """Settings válidos apuntando a directorios temporales (con API key dummy en env)."""
    monkeypatch.setenv("API_FOOTBALL_KEY", "dummy-test-key")
    from src.ingestion.config import get_settings

    s = get_settings()
    s.BRONZE_DIR = tmp_path / "bronze"
    s.CACHE_DIR = tmp_path / "bronze" / "_cache"
    s.RATE_MAX_RETRIES = 2
    s.RATE_BACKOFF_SECONDS = 0.01
    return s
