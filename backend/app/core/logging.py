"""Structured logging + request correlation.

WHY structlog: every debugging mission in this game teaches "logs are data, not
prose". The backend practises what it preaches — one event per log line, with
``request_id`` bound via a contextvar so the ID flows into every log emitted
while handling a request without being threaded through function signatures.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")


def _inject_context(_logger: Any, _name: str, event_dict: dict) -> dict:
    event_dict.setdefault("request_id", request_id_ctx.get())
    uid = user_id_ctx.get()
    if uid != "-":
        event_dict.setdefault("user_id", uid)
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure stdlib logging and structlog to share one pipeline."""
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _inject_context,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[*shared_processors, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    # Uvicorn duplicates access logs; we emit our own with timing + request_id.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
    for noisy in ("sqlalchemy.engine.Engine", "asyncio", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
