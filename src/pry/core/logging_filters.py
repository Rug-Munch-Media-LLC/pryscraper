# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Log-record filtering and transport-noise muting.

Split out of ``logging_config`` on 2026-10-23: that module is grandfathered at
315 lines by the quality gate, so anything added to it has to move elsewhere.
"""

from __future__ import annotations

import logging
import os
from typing import Any

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


def filter_reserved_extras(_: Any, __: Any, event_dict: dict[str, Any]) -> dict[str, Any]:
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


def mute_transport_noise() -> None:
    """Silence httpx/httpcore request chatter.

    httpx logs one INFO line per outbound request ("HTTP Request: POST ..."),
    including every 5s health probe: 77 of 460 lines in a 10-minute sample
    (2026-10-23). Transport chatter, not application telemetry.
    """
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


__all__ = ["filter_reserved_extras", "mute_transport_noise"]
