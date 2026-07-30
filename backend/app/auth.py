"""全局 API Key 鉴权依赖。

支持两种传递方式（优先级从高到低）：
  1. Header: X-API-Key: <key>
  2. Query:  ?api_key=<key>

配置项 NEWS_API_KEY 为空时不启用鉴权（仅限开发环境）。
"""

import hashlib
import hmac
import logging
import time
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


# ════════════════════════════════════════════════════════════
# 模块级访问令牌（模拟仓 / SEPA 私密数据的无状态 HMAC token）
# ════════════════════════════════════════════════════════════
#
# 背景：此前 verify-access 只校验密码、不下发凭证，私密 GET 端点仅靠
# 全局 API Key（而该 Key 编译进公开 H5 bundle，等同公开），"私密"是假的。
#
# 设计：verify-access 验密后签发 token = "{expiry_ts}.{hmac_sha256(scope:expiry_ts)}"
# - 密钥 = SANDBOX_PASSWORD + scope（改密码即全部失效；scope 间互不通）；
# - 无状态，无需存储；7 天过期；
# - 前端解锁后存 token（不再明文存密码），请求头 X-Access-Token 携带；
# - 浏览器直开的导出链接用 query 参数 access_token 传递。

_ACCESS_TOKEN_TTL = 7 * 24 * 3600  # 7 天


def _scope_secret(scope: str) -> bytes:
    return (settings.SANDBOX_PASSWORD + "|" + scope).encode()


def issue_access_token(scope: str) -> str:
    """签发 scope 访问令牌（格式: expiry_ts.hexsig）。"""
    exp = int(time.time()) + _ACCESS_TOKEN_TTL
    sig = hmac.new(
        _scope_secret(scope), f"{scope}:{exp}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{exp}.{sig}"


def verify_access_token(scope: str, token: str | None) -> bool:
    """校验 scope 访问令牌。未配置 SANDBOX_PASSWORD 时放行（开发环境）。"""
    if not settings.SANDBOX_PASSWORD:
        return True
    if not token:
        return False
    try:
        exp_str, sig = token.split(".", 1)
        exp = int(exp_str)
    except (ValueError, AttributeError):
        return False
    if exp < int(time.time()):
        return False
    expected = hmac.new(
        _scope_secret(scope), f"{scope}:{exp}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


def require_scope_token(scope: str):
    """生成校验 scope token 的 FastAPI 依赖。

    接受 Header `X-Access-Token` 或 query 参数 `access_token`（浏览器直开导出用）。
    未配置 SANDBOX_PASSWORD 时放行（生产由 config fail-fast 强制配置）。
    """

    async def _dep(request: Request) -> None:
        if not settings.SANDBOX_PASSWORD:
            return
        token = request.headers.get("X-Access-Token") or request.query_params.get(
            "access_token"
        )
        if not verify_access_token(scope, token):
            logger.warning(
                "Scope token 缺失或无效: scope=%s %s %s",
                scope, request.method, request.url.path,
            )
            raise HTTPException(
                status_code=403,
                detail={"error": "forbidden", "message": "访问令牌缺失或已过期"},
            )

    return _dep
