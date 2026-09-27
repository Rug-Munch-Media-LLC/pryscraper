"""Tiny TTL cache for treasury balance probes.

Split from ``earnings_treasury`` so the balance module stays about balances.
These probes hit rate-limited third-party APIs (Etherscan, Solana RPC), so the
cache is what keeps a dashboard refresh from becoming an API-ban.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import time
from typing import Any

TREASURY_CACHE_TTL_S = 300.0  # 5 minutes

_treasury_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _cached(key: str) -> dict[str, Any] | None:
    hit = _treasury_cache.get(key)
    if hit and (time.monotonic() - hit[0]) < TREASURY_CACHE_TTL_S:
        return hit[1]
    return None


def _store(key: str, value: dict[str, Any]) -> dict[str, Any]:
    _treasury_cache[key] = (time.monotonic(), value)
    return value
