"""Settings loaded from the environment (and the repo-root .env in development)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    app_name: str = "VYNZO API"
    environment: str = "development"
    database_url: str = "postgresql://market:CHANGE_ME@localhost:5432/market"
    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
