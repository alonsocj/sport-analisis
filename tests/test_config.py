"""R1 — API key desde entorno; falla si falta."""

import pytest

from src.ingestion.config import MissingApiKeyError, get_settings


def test_api_key_required(monkeypatch):
    # R1: sin API_FOOTBALL_KEY debe fallar claro y no llamar a nada.
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        get_settings()


def test_api_key_loaded_from_env(monkeypatch):
    # R1: con la variable definida, se carga desde el entorno.
    monkeypatch.setenv("API_FOOTBALL_KEY", "abc-123")
    settings = get_settings()
    assert settings.API_FOOTBALL_KEY == "abc-123"
