"""AlphaReader – FastAPI application entry point."""

import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import v1_router
from app.config import settings
from app.database import Base, engine
import app.models  # noqa: F401 — ensure all ORM models register with Base.metadata
from app.logging_config import setup_logging
from app.middleware.request_id import RequestIDMiddleware, get_request_id
from app.redis import close_redis, init_redis
from app.services.scheduler import start_scheduler, stop_scheduler

# ── Logging (must be called before any logger usage) ──
setup_logging()
logger = logging.getLogger("alphareader")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup & shutdown lifecycle hooks."""
    # ── Startup ──
    logger.info("Starting AlphaReader v0.1.0 [%s]", settings.APP_ENV)

    # In development, auto-create tables for convenience.
    # In production, use Alembic: `alembic upgrade head`
    if settings.APP_ENV != "production":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured (dev mode — use `alembic upgrade head` in production)")
    else:
        logger.info("Production mode — skipping create_all (use Alembic migrations)")

    await init_redis()
    logger.info("Redis connected")

    # Start the periodic news pipeline scheduler
    await start_scheduler()

    yield

    # ── Shutdown ──
    stop_scheduler()
    await close_redis()
    await engine.dispose()
    logger.info("AlphaReader shutdown complete")


app = FastAPI(
    title="AlphaReader",
    description="High-frequency financial intelligence pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Middleware (order matters: first added = outermost) ──
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

app.include_router(v1_router)

# ── Dashboard（统计仪表盘，密码保护）──
from app.dashboard import router as dashboard_router
app.include_router(dashboard_router)

# ── 模拟仓后台管理（复用 Dashboard 认证）──
from app.sandbox_admin import router as sandbox_admin_router
app.include_router(sandbox_admin_router)

# ── API 文档页面 ──
from app.api_docs import router as api_docs_router
app.include_router(api_docs_router)

# ── Debug Panel (only in DEBUG mode) ──
if settings.DEBUG:
    from app.debug_panel import router as debug_router
    app.include_router(debug_router)


# ── Global Exception Handlers ──

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return a clean 422 with structured error details."""
    rid = get_request_id()
    logger.warning("[%s] Validation error on %s %s: %s", rid, request.method, request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "detail": exc.errors(),
            "path": str(request.url.path),
            "request_id": rid,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all handler — log the full traceback, return a safe 500 response."""
    rid = get_request_id()
    logger.error(
        "[%s] Unhandled exception on %s %s: %s\n%s",
        rid, request.method, request.url.path, exc,
        traceback.format_exc(),
    )
    content = {
        "error": "internal_server_error",
        "detail": "An unexpected error occurred. Please try again later.",
        "path": str(request.url.path),
        "request_id": rid,
    }
    # In development, include the actual error message for easier debugging
    if settings.DEBUG:
        content["debug_message"] = str(exc)
        content["debug_type"] = type(exc).__name__
    return JSONResponse(status_code=500, content=content)


@app.get("/", tags=["root"])
async def root():
    return {
        "service": "AlphaReader",
        "version": "0.1.0",
        "env": settings.APP_ENV,
    }
