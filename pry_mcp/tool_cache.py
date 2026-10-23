"""Pry - MCP hot-tool dispatch cache.

Hot tools get a dispatch-level 10s memo (same TTL as the data packages'
``_http_cache``). Entries expire lazily on read and the dict is capped at
``_HOT_TOOL_CACHE_MAX`` (LRU by insertion order).

Split out of ``tool_registry`` so the memo policy is one file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import time
from typing import Any

_HOT_TOOL_CACHE_MAX = 128
_hot_tool_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_HOT_TOOLS_10S = frozenset({"pry_odds", "pry_serp", "pry_live_odds", "pry_scores", "pry_alerts"})
# Argument keys that identify the caller. The 10s memo must never let one
# tenant's paid response be served to another on identical arguments.
_IDENTITY_KEYS = ("api_key", "apikey", "tenant", "tenant_id", "auth", "caller_id")


def identity_of(arguments: dict[str, Any], identity: str | None = None) -> str:
    """Caller namespace for the hot cache: explicit, else an argument, else public."""
    if identity:
        return str(identity)
    for name in _IDENTITY_KEYS:
        value = arguments.get(name)
        if value:
            return str(value)
    return "public"


def _cache_key(name: str, arguments: dict[str, Any], identity: str | None) -> tuple[str, str, str]:
    """Tenant-scoped, order-insensitive key for one tool call."""
    return (
        name,
        identity_of(arguments, identity),
        json.dumps(arguments, sort_keys=True, default=str),
    )


def hot_cache_get(
    name: str, arguments: dict[str, Any], identity: str | None = None
) -> dict[str, Any] | None:
    """Return a fresh (<=10s) cached MCP result for a hot tool, else None."""
    key = _cache_key(name, arguments, identity)
    entry = _hot_tool_cache.get(key)
    if entry is None:
        return None
    cached_at, result = entry
    if time.monotonic() - cached_at < 10.0:
        return result
    _hot_tool_cache.pop(key, None)
    return None


def hot_cache_set(
    name: str, arguments: dict[str, Any], result: dict[str, Any], identity: str | None = None
) -> None:
    """Memoize an MCP result for a hot tool for 10 seconds (bounded LRU)."""
    if len(_hot_tool_cache) >= _HOT_TOOL_CACHE_MAX:
        # Drop the oldest entry (dicts preserve insertion order).
        _hot_tool_cache.pop(next(iter(_hot_tool_cache)))
    _hot_tool_cache[_cache_key(name, arguments, identity)] = (time.monotonic(), result)
