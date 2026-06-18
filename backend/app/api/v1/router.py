"""Aggregate all v1 routers."""

from fastapi import APIRouter, Depends

from app.api.v1.analytics import router as analytics_router
from app.api.v1.briefings import router as briefings_router
from app.api.v1.bridge import router as bridge_router
from app.api.v1.catalyst import router as catalyst_router
from app.api.v1.digests import router as digests_router
from app.api.v1.health import router as health_router
from app.api.v1.news import router as news_router
from app.api.v1.reports import router as reports_router
from app.api.v1.sandbox import router as sandbox_router
from app.api.v1.sepa import router as sepa_router
from app.api.v1.stocks import router as stocks_router
from app.auth import require_api_key

v1_router = APIRouter(prefix="/api/v1")

# health 不需要鉴权（负载均衡/监控探针用）
v1_router.include_router(health_router)

# 其他所有路由都需要 API Key
_protected = APIRouter(dependencies=[Depends(require_api_key)])
_protected.include_router(news_router)
_protected.include_router(bridge_router)
_protected.include_router(reports_router)
_protected.include_router(digests_router)
_protected.include_router(briefings_router)
_protected.include_router(stocks_router)
_protected.include_router(sandbox_router)
_protected.include_router(sepa_router)
_protected.include_router(analytics_router)
_protected.include_router(catalyst_router)

v1_router.include_router(_protected)
