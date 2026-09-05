"""In-memory result caches for crypto_market providers.

A single TTL-keyed dict caches normalized result lists (~30s default) so
free-tier APIs are not hammered; a separate cache holds the (large)
CoinGecko platform map for an hour. ``_clear_cache`` resets everything
and is used by tests.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import time
from typing import Any

CACHE_TTL_SECONDS = 30.0  # in-memory result cache TTL
COINGECKO_LIST_TTL = 3600.0  # /coins/list platform map is big — cache longer
CHAIN_CONTEXT_TTL = 300.0  # DefiLlama chain context TTL

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_platform_cache: dict[str, set[str]] = {}
_platform_cache_ts: float = 0.0


def _cache_get(key: str, ttl: float) -> list[dict[str, Any]] | None:
    """Return a shallow copy of a cached list, or None when expired/missing."""
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > ttl:
        _cache.pop(key, None)
        return None
    return [dict(item) for item in value]


def _cache_set(key: str, value: list[dict[str, Any]]) -> None:
    """Store a shallow copy of a list under ``key``."""
    _cache[key] = (time.monotonic(), [dict(item) for item in value])


def _clear_cache() -> None:
    """Clear all in-memory caches (used by tests)."""
    global _platform_cache_ts
    _cache.clear()
    _platform_cache.clear()
    _platform_cache_ts = 0.0


__all__ = [
    "CACHE_TTL_SECONDS",
    "CHAIN_CONTEXT_TTL",
    "COINGECKO_LIST_TTL",
    "_cache_get",
    "_cache_set",
    "_clear_cache",
]
