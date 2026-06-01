"""Application configuration, loaded from environment / .env."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "GridClean"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)

    # Database (async SQLAlchemy URL)
    database_url: str = Field(
        default="postgresql+asyncpg://gridclean:gridclean@localhost:5433/gridclean",
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Rate limiting
    anonymous_rate_limit_per_min: int = Field(default=30)
    # Default response cache TTL (seconds) for /now and /compare.
    cache_ttl_seconds: int = Field(default=300)

    # External APIs (filled in later phases)
    eia_api_key: str | None = Field(default=None)
    anthropic_api_key: str | None = Field(default=None)

    # AI layer
    # Default to the most capable model; set AI_MODEL=claude-sonnet-4-6 to cut cost.
    ai_model: str = Field(default="claude-opus-4-8")
    # Read-only DB role used to execute AI-generated SQL (created by migration).
    ai_db_user: str = Field(default="gridclean_ro")
    ai_db_password: str = Field(default="gridclean_ro_pw")


@lru_cache
def get_settings() -> Settings:
    return Settings()
