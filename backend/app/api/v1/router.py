"""Aggregate all v1 routers."""

from fastapi import APIRouter

from app.api.v1.bridge import router as bridge_router
from app.api.v1.health import router as health_router
from app.api.v1.news import router as news_router
from app.api.v1.reports import router as reports_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(health_router)
v1_router.include_router(news_router)
v1_router.include_router(bridge_router)
v1_router.include_router(reports_router)
