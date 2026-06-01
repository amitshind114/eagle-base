"""Eagle-Base Configuration Manager.

Loads and validates all environment variables and app settings.
All other modules should import config from here.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseSettings

load_dotenv()

ROOT_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    app_env: str = "development"
    app_debug: bool = True
    app_port: int = 8000

    # Broker
    angel_api_key: str = ""
    angel_client_id: str = ""
    angel_password: str = ""
    angel_totp_secret: str = ""

    # AI
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    """Return application settings singleton."""
    return Settings()


settings = get_settings()
