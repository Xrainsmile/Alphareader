"""Shared fixtures for AlphaReader tests.

Provides:
  - Async test support via pytest-asyncio
  - Isolated in-memory SQLite DB for API tests (with PG type adaptors)
  - Mocked Redis for tests that touch Redis
  - FastAPI TestClient via httpx
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import String, TypeDecorator, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db


# ── SQLite ↔ PostgreSQL type adaptors ──
from sqlalchemy.dialects.postgresql import ARRAY, UUID, JSONB, TSVECTOR
from sqlalchemy.ext.compiler import compiles


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(TSVECTOR, "sqlite")
def _compile_tsvector_sqlite(type_, compiler, **kw):
    return "TEXT"


# Patch ARRAY so SQLite can bind/result-process list ↔ JSON string
_orig_array_bind = ARRAY.bind_processor
_orig_array_result = ARRAY.result_processor


def _array_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return None
            return json.dumps(value)
        return process
    if _orig_array_bind:
        return _orig_array_bind(self, dialect)
    return None


def _array_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return None
            return json.loads(value)
        return process
    if _orig_array_result:
        return _orig_array_result(self, dialect, coltype)
    return None


ARRAY.bind_processor = _array_bind_processor
ARRAY.result_processor = _array_result_processor


# ── In-memory SQLite async engine for isolation ──
_test_engine = create_async_engine(
    "sqlite+aiosqlite:///",  # in-memory
    echo=False,
)
_TestSession = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _setup_db():
    """Create tables before each test, drop after."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an isolated async DB session for direct DB tests."""
    async with _TestSession() as session:
        yield session


@pytest.fixture
def mock_redis():
    """Return an AsyncMock that mimics a Redis client."""
    r = AsyncMock()
    r.ping.return_value = True
    r.hgetall.return_value = {}
    r.sadd.return_value = 1
    r.sismember.return_value = False
    r.smembers.return_value = set()
    r.delete.return_value = 1
    r.pipeline.return_value = AsyncMock()
    return r


@pytest.fixture
async def client(mock_redis) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client hitting the real FastAPI app with test DB + mock Redis."""
    from app.main import app
    from app.config import settings

    # Override dependencies
    async def _override_get_db():
        async with _TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    # Disable API key auth in tests (avoid depending on local .env)
    original_api_key = settings.NEWS_API_KEY
    settings.NEWS_API_KEY = ""

    # Patch redis at module level
    import app.redis as redis_mod
    original_pool = redis_mod.redis_pool
    redis_mod.redis_pool = mock_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    # Restore
    settings.NEWS_API_KEY = original_api_key
    redis_mod.redis_pool = original_pool
    app.dependency_overrides.clear()
