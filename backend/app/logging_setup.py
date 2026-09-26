"""Structured logging with request-scoped context.

- ``LOG_FORMAT=json`` (default in prod images) → one JSON object per line.
- ``LOG_FORMAT=console`` → pretty, colorized, human-readable (dev default).

Every log line inside a request scope includes ``request_id``. The middleware
in ``backend.app.main`` generates a UUID per request (or uses the client's
``X-Request-ID`` header if provided) and writes it back on the response.
"""

from __future__ import annotations

import contextvars
import logging
import os
import sys

import structlog


# Request-scoped context. Set by the middleware; read by the processor below.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def _inject_request_id(_logger, _method, event_dict):
    rid = request_id_var.get("")
    if rid:
        event_dict["request_id"] = rid
    return event_dict


def configure_logging() -> None:
    """Wire stdlib logging + structlog. Call once at app startup."""
    fmt = os.environ.get("LOG_FORMAT", "console").lower()
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_request_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if fmt == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers (uvicorn, fastapi, etc.) through structlog too.
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet the uvicorn.access logger — middleware will log requests with
    # request_id + structured fields, which is what we actually want.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
