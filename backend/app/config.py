"""Centralized configuration via pydantic-settings."""

from pydantic import computed_field
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
    TIMEZONE: str = "Asia/Shanghai"

    # CORS
    CORS_ORIGINS: str = "*"  # comma-separated, e.g. "https://example.com,http://localhost:3000"

    # DeepSeek
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_URL: str = "https://api.deepseek.com/v1/chat/completions"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_BATCH_SIZE: int = 20
    DEEPSEEK_SCORE_THRESHOLD: int = 6
    DEEPSEEK_MAX_RETRIES: int = 2

    # Scheduler
    PIPELINE_INTERVAL_HOURS: int = 2

    # PostgreSQL
    POSTGRES_USER: str = "alphareader"
    POSTGRES_PASSWORD: str = "changeme"
    POSTGRES_DB: str = "alphareader"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_HOST: str = "cache"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_MAX_CONNECTIONS: int = 20

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Dynamically build the async PostgreSQL DSN from individual fields."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        """Dynamically build the Redis DSN from individual fields."""
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse CORS_ORIGINS into a list."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
