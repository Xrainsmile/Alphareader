"""Centralized configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_ENV: str = "development"
    DEBUG: bool = True

    # DeepSeek
    DEEPSEEK_API_KEY: str = ""

    # PostgreSQL
    POSTGRES_USER: str = "alphareader"
    POSTGRES_PASSWORD: str = "changeme"
    POSTGRES_DB: str = "alphareader"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = "postgresql+asyncpg://alphareader:changeme@db:5432/alphareader"

    # Redis
    REDIS_HOST: str = "cache"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://cache:6379/0"


settings = Settings()
