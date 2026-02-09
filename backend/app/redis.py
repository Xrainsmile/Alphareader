"""Async Redis connection pool."""

import redis.asyncio as aioredis

from app.config import settings

redis_pool: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """Create and return the global Redis connection pool."""
    global redis_pool
    redis_pool = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
    )
    return redis_pool


async def close_redis() -> None:
    """Gracefully close the Redis connection pool."""
    global redis_pool
    if redis_pool:
        await redis_pool.aclose()
        redis_pool = None


def get_redis() -> aioredis.Redis:
    """Get the current Redis connection (for use in dependencies)."""
    if redis_pool is None:
        raise RuntimeError("Redis pool not initialized")
    return redis_pool
