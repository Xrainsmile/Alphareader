"""AlphaReader – FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import v1_router
from app.config import settings
from app.database import Base, engine
from app.redis import close_redis, init_redis
from app.services.scheduler import start_scheduler, stop_scheduler

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-28s | %(levelname)-5s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("alphareader")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup & shutdown lifecycle hooks."""
    # ── Startup ──
    logger.info("Starting AlphaReader v0.1.0 [%s]", settings.APP_ENV)

    # Create tables (dev convenience; use Alembic migrations in prod)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")

    await init_redis()
    logger.info("Redis connected")

    # Start the periodic news pipeline scheduler
    start_scheduler()

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

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Docker 内网 + 开发环境; 生产环境改为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)


@app.get("/", tags=["root"])
async def root():
    return {
        "service": "AlphaReader",
        "version": "0.1.0",
        "env": settings.APP_ENV,
    }
