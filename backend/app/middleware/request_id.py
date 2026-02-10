"""Request-ID middleware — assigns a unique ID to every request.

The ID is:
  1. Stored in a ContextVar so any logger in the same async task can read it.
  2. Added as a response header ``X-Request-ID``.
  3. Accepts an incoming ``X-Request-ID`` header (from API gateway / load balancer)
     and reuses it instead of generating a new one.

Usage in business code:
    from app.middleware.request_id import get_request_id
    rid = get_request_id()   # returns current request's ID or "-"
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

logger = logging.getLogger("alphareader.middleware")


def get_request_id() -> str:
    """Return the current request's ID (or ``"-"`` outside a request context)."""
    return _request_id_ctx.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject a unique request ID into every request/response cycle."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Accept upstream header or generate a short UUID
        incoming = request.headers.get("x-request-id")
        request_id = incoming or uuid.uuid4().hex[:12]

        # Store in ContextVar so log filters / business code can access it
        token = _request_id_ctx.set(request_id)

        # Also attach to request.state for convenience in route handlers
        request.state.request_id = request_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            _request_id_ctx.reset(token)

        response.headers["X-Request-ID"] = request_id

        # Access log
        logger.info(
            "%s %s %s %.1fms [%s]",
            request_id,
            request.method,
            request.url.path,
            elapsed_ms,
            response.status_code,
        )

        return response
