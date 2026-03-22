"""Alembic env.py — async migration runner for AlphaReader.

Reads DATABASE_URL from app.config.settings (which loads .env).
Supports both offline (SQL script) and online (async connection) modes.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── AlphaReader imports ──
from app.config import settings
from app.database import Base

# Import all models so Alembic can detect them for autogenerate
from app.models.news import News  # noqa: F401
from app.models.report import Report  # noqa: F401
from app.models.stock import StockDailyQuote, StockRSRating  # noqa: F401
from app.models.analytics import AnalyticsDaily, PipelineRun  # noqa: F401
from app.models.sandbox import SandboxStock, SandboxAnalysis, SandboxTrade, SandboxNav  # noqa: F401
from app.models.screener import ScreenerRun, WatchlistDaily, TrendScreenerRun, TrendWatchlistDaily  # noqa: F401
from app.models.catalyst import NewsCatalystStock  # noqa: F401
from app.models.news_digest import NewsDigest  # noqa: F401
from app.models.daily_briefing import DailyBriefing  # noqa: F401

# ── Alembic Config ──
config = context.config

# Override sqlalchemy.url from app settings (async DSN)
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations — delegates to async runner."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
