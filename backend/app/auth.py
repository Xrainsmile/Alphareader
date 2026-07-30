"""全局 API Key 鉴权依赖。

支持两种传递方式（优先级从高到低）：
  1. Header: X-API-Key: <key>
  2. Query:  ?api_key=<key>

配置项 NEWS_API_KEY 为空时不启用鉴权（仅限开发环境）。
"""

import hmac
import logging
from fastapi import Depends, HTTPException, Query, Request, Security
from fastapi.security import APIKeyHeader

from app.config import settings

logger = logging.getLogger("alphareader.auth")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    header_key: str | None = Security(_api_key_header),
    query_key: str | None = Query(None, alias="api_key", include_in_schema=False),
) -> str | None:
    """验证 API Key，返回有效的 key 或在未配置时跳过。"""
    # 未配置 NEWS_API_KEY 则跳过鉴权（开发环境）
    if not settings.NEWS_API_KEY:
        return None

    api_key = header_key or query_key

    if not api_key:
        logger.warning("请求缺少 API Key: %s %s", request.method, request.url.path)
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "缺少 API Key，请在 Header 中传递 X-API-Key 或 Query 中传递 api_key"},
        )

    if not hmac.compare_digest(api_key.encode(), settings.NEWS_API_KEY.encode()):
        logger.warning("无效的 API Key: %s %s", request.method, request.url.path)
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "message": "API Key 无效"},
        )

    return api_key


_admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def require_admin_key(
    request: Request,
    admin_key: str | None = Security(_admin_key_header),
) -> str | None:
    """高成本/管理类触发端点的独立鉴权（Header: X-Admin-Key）。

    用于手动生成 digest/briefing、手动触发 pipeline、行情回填等烧钱/重资源端点。
    叠加在全局 X-API-Key 之上（两个 Header 都要传）。

    - 配置 ADMIN_API_KEY：强制校验，缺失/不匹配一律 403；
    - 未配置：放行（由全局 require_api_key 兜底；生产环境由 config 启动校验强制配置）。
    """
    if settings.ADMIN_API_KEY:
        if not admin_key or not hmac.compare_digest(
            admin_key.encode(), settings.ADMIN_API_KEY.encode()
        ):
            logger.warning("Admin Key 缺失或无效: %s %s", request.method, request.url.path)
            raise HTTPException(
                status_code=403,
                detail={"error": "forbidden", "message": "Admin Key 缺失或无效"},
            )
        return admin_key
    return None
