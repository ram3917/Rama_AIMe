"""Centralized configuration. Every env var the app reads lives here,
loaded once from .env via pydantic-settings. Nothing is required at
import time - callers that need a specific secret check for it and
raise a clear error at the point of use.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str | None = None
    garmin_email: str | None = None
    garmin_password: str | None = None

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    personal_db_path: Path = REPO_ROOT / "data" / "personal.db"
    fitness_db_path: Path = REPO_ROOT / "data" / "fitness.db"
    meals_db_path: Path = REPO_ROOT / "data" / "meals.db"
    checkpoint_db_path: Path = REPO_ROOT / "data" / "checkpoints.db"
    log_level: str = "INFO"


settings = Settings()
