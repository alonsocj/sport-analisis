"""Cliente HTTP API-Football: caché local + backoff 429 + manejo de errores.

Cubre R6 (caché), R7 (rate limit/backoff) y la base de R9 (errores HTTP).
El transporte HTTP y la función ``sleep`` son inyectables para que los tests corran
offline, deterministas y sin consumir la cuota real.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from .bronze import param_key
from .config import Settings


class _Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


# transport: (method, url, headers, params) -> _Response
Transport = Callable[[str, str, dict[str, str], dict[str, Any]], _Response]


class RateLimitError(RuntimeError):
    """429 persistente tras agotar reintentos (R7)."""


class HttpError(RuntimeError):
    """Respuesta HTTP no exitosa distinta de 429 (R9)."""

    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code


def _default_transport(method: str, url: str, headers: dict[str, str], params: dict[str, Any]) -> _Response:
    """Transporte real con requests (import perezoso: solo si se usa)."""
    import requests  # noqa: PLC0415  (perezoso a propósito)

    return requests.request(method, url, headers=headers, params=params, timeout=30)


class ApiFootballClient:
    """Cliente con caché en disco y backoff exponencial ante 429."""

    def __init__(
        self,
        settings: Settings,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._transport = transport or _default_transport
        self._sleep = sleep

    # --- caché (R6) ---
    def _cache_file(self, endpoint: str, params: dict[str, Any]) -> Path:
        endpoint_dir = endpoint.strip("/").replace("/", "_")
        return Path(self.settings.CACHE_DIR) / endpoint_dir / f"{param_key(params)}.json"

    def _read_cache(self, endpoint: str, params: dict[str, Any]) -> Any | None:
        f = self._cache_file(endpoint, params)
        if f.is_file():
            return json.loads(f.read_text(encoding="utf-8"))
        return None

    def _write_cache(self, endpoint: str, params: dict[str, Any], payload: Any) -> None:
        f = self._cache_file(endpoint, params)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # --- request ---
    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """GET con caché y backoff. Devuelve el JSON de la respuesta.

        R6: si hay caché, la sirve sin llamar HTTP.
        R7: ante 429 reintenta con backoff exponencial; agotados → RateLimitError.
        R9: status no exitoso (≠2xx, ≠429) → HttpError.
        """
        params = params or {}

        cached = self._read_cache(endpoint, params)
        if cached is not None:
            return cached

        url = f"{self.settings.API_FOOTBALL_BASE_URL.rstrip('/')}/{endpoint.strip('/')}"
        headers = {"x-apisports-key": self.settings.API_FOOTBALL_KEY}

        attempts = self.settings.RATE_MAX_RETRIES + 1
        for attempt in range(attempts):
            resp = self._transport("GET", url, headers, params)
            status = resp.status_code

            if 200 <= status < 300:
                payload = resp.json()
                self._write_cache(endpoint, params, payload)
                return payload

            if status == 429:
                if attempt < attempts - 1:
                    self._sleep(self.settings.RATE_BACKOFF_SECONDS * (2 ** attempt))
                    continue
                raise RateLimitError(
                    f"429 persistente en {endpoint} tras {attempts} intentos"
                )

            raise HttpError(status, f"Error HTTP {status} en {endpoint}")

        # inalcanzable, pero por exhaustividad
        raise RateLimitError(f"sin respuesta válida para {endpoint}")
