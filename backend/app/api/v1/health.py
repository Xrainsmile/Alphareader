"""Health-check endpoint – verifies DB & Redis connectivity."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.redis import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Return service status including DB and Redis connectivity."""
    status = {"status": "ok", "postgres": "ok", "redis": "ok"}

    # Check PostgreSQL
    # 注意：异常详情只记日志不回前端——health 是公开端点，
    # 原始错误可能含内网地址/连接串等敏感信息。
    import logging

    _logger = logging.getLogger("alphareader.health")
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        _logger.warning("health check postgres failed: %s", e)
        status["postgres"] = "error"
        status["status"] = "degraded"

    # Check Redis
    try:
        r = get_redis()
        pong = await r.ping()
        if not pong:
            raise ConnectionError("Redis ping returned False")
    except Exception as e:
        _logger.warning("health check redis failed: %s", e)
        status["redis"] = "error"
        status["status"] = "degraded"

    if status["status"] == "degraded":
        return JSONResponse(content=status, status_code=503)
    return status
