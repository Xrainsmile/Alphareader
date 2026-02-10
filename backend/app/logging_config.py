"""Centralized logging configuration for AlphaReader.

Supports:
  - LOG_LEVEL env var (DEBUG / INFO / WARNING / ERROR / CRITICAL)
  - LOG_FORMAT env var ("text" for human-readable, "json" for structured)
  - JSON mode outputs one JSON object per line (for log aggregation services)
  - Automatic request_id injection from RequestIDMiddleware ContextVar
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.config import settings


class _RequestIDFilter(logging.Filter):
    """Inject ``request_id`` into every LogRecord from the ContextVar."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Lazy import to avoid circular dependency (middleware → logging_config)
        from app.middleware.request_id import get_request_id  # noqa: WPS433

        record.request_id = get_request_id()
        return True


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
                    .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_entry["stack"] = record.stack_info
        return json.dumps(log_entry, ensure_ascii=False)


_TEXT_FORMAT = (
    "%(asctime)s | %(name)-28s | %(levelname)-5s | [%(request_id)s] %(message)s"
)
_TEXT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Configure the root logger based on settings.LOG_LEVEL and settings.LOG_FORMAT."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Remove any existing handlers on root logger (e.g. from basicConfig)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # Attach request_id filter so every log line carries the current request ID
    handler.addFilter(_RequestIDFilter())

    if settings.LOG_FORMAT.lower() == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT, datefmt=_TEXT_DATEFMT))

    root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "asyncio", "urllib3", "watchfiles"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    logging.getLogger("alphareader").info(
        "Logging configured: level=%s, format=%s", settings.LOG_LEVEL, settings.LOG_FORMAT,
    )
