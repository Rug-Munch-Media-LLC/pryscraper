"""Pry - structured logging configuration (structlog + JSON).

Per CONVENTIONS.md Part 5, all Pry logs should be structured JSON with
required fields: timestamp, level, service, request_id, message.

This module is the central place to configure logging. Call `setup_logging()`
once at process startup (e.g., in `cli.py:main()` or `api.py` lifespan).

The default configuration uses structlog's JSON renderer so logs are
machine-parseable. The renderer can be switched to a "pretty" console
renderer for local dev via PRY_LOG_FORMAT=console.

Backward compatibility: code that does `logging.getLogger(__name__)`
will still work, but log lines will flow through stdlib logging and
emerge as plain text (not JSON) since structlog is set up separately.
To get JSON from stdlib loggers too, install a `structlog.stdlib.ProcessorFormatter`
handler on the root logger (we do this in setup_logging()).

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
import sys
from typing import Any

try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:  # pragma: no cover
    _HAS_STRUCTLOG = False


# ── Configuration constants ──
DEFAULT_LEVEL = "INFO"
SERVICE_NAME = "pry"
LOG_FORMAT_ENV = "PRY_LOG_FORMAT"  # "json" (default) or "console"
LOG_LEVEL_ENV = "PRY_LOG_LEVEL"  # "DEBUG", "INFO", "WARNING", "ERROR"

_configured = False


def _resolve_level() -> int:
    """Resolve the log level from env, defaulting to INFO."""
    name = os.getenv(LOG_LEVEL_ENV, DEFAULT_LEVEL).upper()
    level = getattr(logging, name, None)
    if not isinstance(level, int):
        return logging.INFO
    return level


def _resolve_format() -> str:
    """Resolve the format from env. Default: json (production-safe)."""
    return os.getenv(LOG_FORMAT_ENV, "json").lower()


def setup_logging(level: int | None = None, fmt: str | None = None) -> None:
    """Configure structlog + stdlib logging for Pry.

    Idempotent: calling twice is a no-op (subsequent calls don't reconfigure).

    Args:
        level: Optional log level override. Defaults to PRY_LOG_LEVEL env or INFO.
        fmt: Optional format override: "json" (default) or "console".
    """
    global _configured
    if _configured:
        return
    if not _HAS_STRUCTLOG:
        # Fall back to stdlib basic config; user can install structlog for JSON
        logging.basicConfig(
            level=level or _resolve_level(),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            stream=sys.stdout,
        )
        _configured = True
        return

    level = level if level is not None else _resolve_level()
    fmt = fmt or _resolve_format()

    # Shared processors that add the standard fields per CONVENTIONS.md Part 5.
    # Order matters: outer processors wrap inner ones. Timestamps go first.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _filter_reserved_extras,
        _add_service_name,
        _add_request_id_if_present,
    ]

    if fmt == "console":
        # Pretty console renderer for local dev
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # JSON renderer for production (default)
        renderer = structlog.processors.JSONRenderer()

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging through structlog's formatter so plain
    # `logging.getLogger(__name__)` calls also produce JSON/console output
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    # Remove any existing handlers (e.g., uvicorn's) and add ours
    root.handlers = [handler]
    root.setLevel(level)

    _configured = True


def _add_service_name(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Add the service name to every log record (CONVENTIONS.md Part 5)."""
    event_dict.setdefault("service", SERVICE_NAME)
    return event_dict


def _add_request_id_if_present(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Pull request_id from contextvars (set by middleware) if present."""
    # The middleware (or FastAPI dependency) sets this. We don't import
    # the middleware here to avoid circular imports.
    return event_dict


# Reserved stdlib LogRecord attribute names. Code that uses these as keys
# in `logger.info("...", extra={"name": ...})` would normally crash with
# KeyError "Attempt to overwrite 'name' in LogRecord". We strip them in
# the foreign_pre_chain so existing code keeps working. In strict mode
# (PRY_LOG_STRICT_EXTRAS=1) the filtering is disabled and the stdlib
# default behavior takes over.
_RESERVED_LOGRECORD_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


def _filter_reserved_extras(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Filter out reserved LogRecord keys from extra={...} in stdlib log calls.

    Without this, code like `logger.warning("x", extra={"name": "foo"})` would
    raise KeyError because LogRecord already has a 'name' attribute. We move
    the offending keys to a `_extra` sub-dict so they survive the round-trip.
    """
    if os.getenv("PRY_LOG_STRICT_EXTRAS", "").lower() in ("1", "true", "yes"):
        return event_dict  # let stdlib do its thing (and crash if used)
    extras: dict[str, Any] = {}
    for k in list(event_dict.keys()):
        if k in _RESERVED_LOGRECORD_KEYS:
            extras[k] = event_dict.pop(k)
    if extras:
        event_dict["extra"] = extras
    return event_dict


def get_logger(name: str | None = None) -> Any:
    """Get a structlog logger. Falls back to stdlib if structlog isn't installed.

    Usage:
        from logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("event_name", key="value", count=42)
    """
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return logging.getLogger(name or SERVICE_NAME)


def is_configured() -> bool:
    """Whether setup_logging() has been called. Useful for tests."""
    return _configured
