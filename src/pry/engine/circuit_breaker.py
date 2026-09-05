"""Per-domain concurrency semaphores and tier circuit-breaker mapping.

Extracted from ``ultimate_scraper`` so the throttling / breaker policy lives
in one place. The breaker *state* itself is owned by
``pry.engine.resilience.registry``; this module only provides:

* the per-domain asyncio semaphore registry (bounded LRU), and
* the static mapping of external-service tiers to their breaker names.

Callers resolve breaker state through the ``registry`` object they already
hold (tests patch ``ultimate_scraper.registry``, so the lookup must stay at
the call site, not inside this module).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from typing import Any

__all__ = ["BREAKER_FOR_TIER", "DOMAIN_MAX_CONCURRENCY", "domain_semaphore"]

# Per-domain concurrency throttle: cap the number of simultaneous scrapes to
# the SAME domain so a single caller (or a burst of callers) cannot hammer one
# target site with unbounded parallel requests. This protects both the target
# site (good citizenship / avoiding IP bans) and our own outbound resources.
# The limit is per-domain, not global — different domains proceed in parallel.
DOMAIN_MAX_CONCURRENCY = 10
# Bounded LRU registry: cap the number of tracked per-domain semaphores so a
# long-running process scraping many distinct domains cannot grow this dict
# without bound. When the cap is exceeded, the least-recently-added entry is
# evicted (OrderedDict.popitem(last=False)).
_DOMAIN_SEMAPHORE_MAX = 500
_domain_semaphores: OrderedDict[str, Any] = OrderedDict()
_domain_semaphores_lock = threading.Lock()

# External service tiers protected by circuit breakers. Tier name -> breaker
# name in the resilience registry.
BREAKER_FOR_TIER: dict[str, str] = {
    "flaresolverr": "flaresolverr",
    "playwright": "playwright",
    "camoufox": "camoufox",
    "tls_fingerprint": "tls_fingerprint",
}


def domain_semaphore(domain: str) -> Any:
    """Return a per-domain asyncio.Semaphore, creating it on first use.

    Thread-safe creation (the semaphore registry is shared across the event
    loop and any worker threads). asyncio.Semaphore is not thread-safe to
    create concurrently, so creation is serialized under a lock.
    """
    with _domain_semaphores_lock:
        sem = _domain_semaphores.get(domain)
        if sem is None:
            sem = asyncio.Semaphore(DOMAIN_MAX_CONCURRENCY)
            _domain_semaphores[domain] = sem
            # LRU eviction: keep the registry bounded.
            if len(_domain_semaphores) > _DOMAIN_SEMAPHORE_MAX:
                _domain_semaphores.popitem(last=False)
        return sem
