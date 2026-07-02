"""Configuración de la ingesta (R1).

La API key se lee SIEMPRE desde la variable de entorno ``API_FOOTBALL_KEY`` y
NUNCA se hardcodea ni se persiste. Usa pydantic-settings si está disponible; si no
(p. ej. entorno con solo pytest instalado), cae a un fallback de stdlib con el mismo
contrato público para mantener los tests verdes offline.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # ruta principal: pydantic-settings (ver requirements.txt)
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        """Config de ingesta leída de variables de entorno."""

        model_config = SettingsConfigDict(env_file=None, extra="ignore")

        API_FOOTBALL_KEY: str
        API_FOOTBALL_BASE_URL: str = "https://v3.football.api-sports.io"
        BRONZE_DIR: Path = Path("data/bronze")
        CACHE_DIR: Path = Path("data/bronze/_cache")
        RATE_MAX_RETRIES: int = 3
        RATE_BACKOFF_SECONDS: float = 1.0

    _USING_PYDANTIC = True

except ImportError:  # fallback stdlib (mismo contrato)
    from dataclasses import dataclass, field

    @dataclass
    class Settings:  # type: ignore[no-redef]
        """Fallback sin pydantic-settings. Mismo contrato público."""

        API_FOOTBALL_KEY: str = ""
        API_FOOTBALL_BASE_URL: str = "https://v3.football.api-sports.io"
        BRONZE_DIR: Path = field(default_factory=lambda: Path("data/bronze"))
        CACHE_DIR: Path = field(default_factory=lambda: Path("data/bronze/_cache"))
        RATE_MAX_RETRIES: int = 3
        RATE_BACKOFF_SECONDS: float = 1.0

    _USING_PYDANTIC = False


class MissingApiKeyError(RuntimeError):
    """Se levanta cuando falta ``API_FOOTBALL_KEY`` (R1)."""


def get_settings() -> Settings:
    """Construye Settings desde el entorno. Falla claro si falta la key (R1).

    SI ``API_FOOTBALL_KEY`` no está definida o está vacía → ``MissingApiKeyError``,
    sin realizar ninguna llamada.
    """
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        raise MissingApiKeyError(
            "Falta la variable de entorno API_FOOTBALL_KEY. "
            "Defínela antes de ingerir datos: export API_FOOTBALL_KEY='...'"
        )

    if _USING_PYDANTIC:
        return Settings()  # pydantic lee el resto del entorno

    # fallback: leer manualmente el resto de variables
    s = Settings(API_FOOTBALL_KEY=key)
    s.API_FOOTBALL_BASE_URL = os.environ.get("API_FOOTBALL_BASE_URL", s.API_FOOTBALL_BASE_URL)
    s.BRONZE_DIR = Path(os.environ.get("BRONZE_DIR", str(s.BRONZE_DIR)))
    s.CACHE_DIR = Path(os.environ.get("CACHE_DIR", str(s.CACHE_DIR)))
    s.RATE_MAX_RETRIES = int(os.environ.get("RATE_MAX_RETRIES", s.RATE_MAX_RETRIES))
    s.RATE_BACKOFF_SECONDS = float(os.environ.get("RATE_BACKOFF_SECONDS", s.RATE_BACKOFF_SECONDS))
    return s
