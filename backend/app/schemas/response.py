"""统一 API 响应格式。

所有 API 端点应使用 APIResponse / PaginatedResponse 包装返回数据，
确保前端只需处理一种数据结构。

用法：
    return APIResponse(data={"id": 1, "name": "test"})
    return APIResponse(code=1, message="参数错误")
    return PaginatedResponse(data=items, total=100, limit=20, offset=0)
"""

from typing import Any

from pydantic import BaseModel


class APIResponse(BaseModel):
    """通用 API 响应包装器。"""
    code: int = 0
    message: str = "ok"
    data: Any = None


class PaginatedResponse(APIResponse):
    """带分页信息的 API 响应包装器。"""
    total: int = 0
    limit: int = 20
    offset: int = 0
