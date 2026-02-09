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
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        status["postgres"] = f"error: {e}"
        status["status"] = "degraded"

    # Check Redis
    try:
        r = get_redis()
        pong = await r.ping()
        if not pong:
            raise ConnectionError("Redis ping returned False")
    except Exception as e:
        status["redis"] = f"error: {e}"
        status["status"] = "degraded"

    if status["status"] == "degraded":
        return JSONResponse(content=status, status_code=503)
    return status
