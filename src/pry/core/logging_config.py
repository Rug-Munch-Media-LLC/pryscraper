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

import structlog

_HAS_STRUCTLOG = True


# ── Configuration constants ──
DEFAULT_LEVEL = "INFO"
SERVICE_NAME = "pry"
LOG_FORMAT_ENV = "PRY_LOG_FORMAT"  # "json" (default) or "console"
LOG_LEVEL_ENV = "PRY_LOG_LEVEL"  # "DEBUG", "INFO", "WARNING", "ERROR"

REQUEST_ID_KEY = "request_id"

_configured = False
# Track the active level so set_log_level() can reconfigure structlog.
_current_level: int = logging.INFO


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


def _shared_processors() -> list[Any]:
    """The processors applied to every log record (structlog + stdlib bridge).

    Order matters: outer processors wrap inner ones. Timestamps go first.
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _filter_reserved_extras,
        _add_service_name,
        _add_request_id_if_present,
    ]


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
    global _current_level
    _current_level = level

    # Shared processors that add the standard fields per CONVENTIONS.md Part 5.
    shared_processors = _shared_processors()

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


def bind_request_id(request_id: str) -> None:
    """Bind a request id into structlog contextvars for this context.

    Every structlog record emitted inside the context (asyncio task /
    thread) will carry ``request_id`` automatically. The ASGI middleware
    (or a FastAPI dependency) should call this once per request.

    Stdlib ``logging.getLogger(...)`` callers can also pass
    ``extra={"request_id": ...}`` — the foreign_pre_chain preserves it.
    """
    if _HAS_STRUCTLOG:
        structlog.contextvars.bind_contextvars(**{REQUEST_ID_KEY: request_id})


def unbind_request_id() -> None:
    """Remove the request id from the current context."""
    if _HAS_STRUCTLOG:
        structlog.contextvars.unbind_contextvars(REQUEST_ID_KEY)


def clear_request_id() -> None:
    """Clear the request id (and any other bound contextvars)."""
    if _HAS_STRUCTLOG:
        structlog.contextvars.clear_contextvars()


def get_log_level() -> int:
    """Return the currently active log level (int, as in the logging module)."""
    return _current_level


def set_log_level(level: int | str) -> None:
    """Override the log level at runtime (e.g. from a debug endpoint).

    Accepts a ``logging`` level int (``logging.DEBUG``) or a level name
    ("DEBUG", "info", ...). Updates the root stdlib logger immediately
    and reconfigures structlog so *newly created* loggers filter at the
    new level. Already-cached structlog loggers keep their original
    wrapper until they are re-created.
    """
    global _current_level
    if isinstance(level, str):
        resolved = getattr(logging, level.upper(), None)
        if not isinstance(resolved, int):
            raise ValueError(f"unknown log level: {level!r}")
        level = resolved
    if not isinstance(level, int):
        raise TypeError("level must be an int or a level name string")

    _current_level = level
    logging.getLogger().setLevel(level)
    if _HAS_STRUCTLOG:
        structlog.configure(
            processors=[
                *_shared_processors(),
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )


def _add_service_name(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Add the service name to every log record (CONVENTIONS.md Part 5)."""
    event_dict.setdefault("service", SERVICE_NAME)
    return event_dict


def _add_request_id_if_present(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Propagate request_id into every structured log record.

    Priority:
      1. An explicit ``request_id`` already in the event (a direct structlog
         kwarg) — preserved.
      2. ``extra={"request_id": ...}`` on a stdlib log call — lives on the
         ``_record`` LogRecord, not the foreign event dict, so it must be
         pulled out of the record.
      3. ``request_id`` bound via ``bind_request_id()`` in structlog
         contextvars (merged in by ``merge_contextvars``).
    """
    request_id = event_dict.get(REQUEST_ID_KEY)
    if not request_id:
        record = event_dict.get("_record")
        if record is not None:
            request_id = getattr(record, REQUEST_ID_KEY, None)
    if not request_id and _HAS_STRUCTLOG:
        ctx = structlog.contextvars.get_contextvars()
        request_id = ctx.get(REQUEST_ID_KEY)
    if request_id:
        event_dict[REQUEST_ID_KEY] = request_id
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
        from pry.core.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("event_name", key="value", count=42)
    """
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return logging.getLogger(name or SERVICE_NAME)


def is_configured() -> bool:
    """Whether setup_logging() has been called. Useful for tests."""
    return _configured
