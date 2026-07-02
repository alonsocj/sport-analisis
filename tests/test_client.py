"""R6 — caché; R7 — backoff ante 429."""

import pytest

from src.ingestion.client import ApiFootballClient, RateLimitError
from tests.conftest import FakeResponse, FakeTransport


def test_cache_hit_skips_http(tmp_settings):
    # Primera llamada: 200 desde transporte; segunda: debe servir de caché sin llamar.
    transport = FakeTransport(queue=[FakeResponse(200, {"response": [1, 2, 3]})])
    client = ApiFootballClient(tmp_settings, transport=transport, sleep=lambda _: None)

    first = client.get("fixtures", {"team": 10, "last": 15})
    second = client.get("fixtures", {"team": 10, "last": 15})

    assert first == second == {"response": [1, 2, 3]}
    # R6: solo 1 llamada HTTP; la segunda salió de caché.
    assert len(transport.calls) == 1


def test_retry_on_429_then_success(tmp_settings):
    # R7: 429 seguido de 200 → reintenta con backoff y devuelve el payload.
    slept: list[float] = []
    transport = FakeTransport(queue=[
        FakeResponse(429, {}),
        FakeResponse(200, {"response": ["ok"]}),
    ])
    client = ApiFootballClient(tmp_settings, transport=transport, sleep=slept.append)

    out = client.get("odds", {"fixture": 1})

    assert out == {"response": ["ok"]}
    assert len(transport.calls) == 2
    assert len(slept) == 1  # esperó una vez antes del reintento


def test_429_exhausts_retries_raises(tmp_settings):
    # R7: 429 persistente agota reintentos → RateLimitError.
    attempts = tmp_settings.RATE_MAX_RETRIES + 1
    transport = FakeTransport(queue=[FakeResponse(429, {}) for _ in range(attempts)])
    client = ApiFootballClient(tmp_settings, transport=transport, sleep=lambda _: None)

    with pytest.raises(RateLimitError):
        client.get("fixtures", {"team": 10, "last": 15})

    assert len(transport.calls) == attempts
