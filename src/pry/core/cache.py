"""Pry — in-memory LRU cache.
Prevents re-scraping the same URL within TTL window."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import hashlib
import json
import time
from collections import OrderedDict

from pry.core.observability import CACHE_HITS


class ResponseCache:
    """In-memory LRU cache with TTL expiry.

    Default TTL: 300 seconds (5 min) for pages, 3600 (1 hr) for API calls.
    """

    def __init__(self, capacity: int = 500):
        self.capacity = capacity
        self._cache: OrderedDict = OrderedDict()
        self._hits = 0
        self._misses = 0

    def _key(self, url: str, options: dict | None = None) -> str:
        """Generate cache key from URL + options."""
        opt_str = json.dumps(options or {}, sort_keys=True)
        raw = f"{url}:{opt_str}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

    def get(self, url: str, options: dict | None = None) -> dict | None:
        """Get cached response if fresh."""
        key = self._key(url, options)
        now = time.time()

        # Check local cache
        if key in self._cache:
            entry = self._cache[key]
            if entry["expires"] > now:
                self._hits += 1
                self._cache.move_to_end(key)
                if CACHE_HITS:
                    CACHE_HITS.labels(cache_type="local").inc()
                return entry["data"]
            else:
                del self._cache[key]

        self._misses += 1
        return None

    def set(self, url: str, data: dict, options: dict | None = None, ttl: int = 300):
        """Cache a response with TTL in seconds."""
        key = self._key(url, options)
        entry = {"data": data, "expires": time.time() + ttl, "cached_at": time.time()}

        # Evict oldest if at capacity
        if len(self._cache) >= self.capacity:
            self._cache.popitem(last=False)

        self._cache[key] = entry

    def stats(self) -> dict:
        """Get cache hit/miss statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "capacity": self.capacity,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0,
        }

    def invalidate(self, url: str):
        """Remove cached entry for a URL."""
        keys_to_remove = [k for k, v in self._cache.items() if v["data"].get("url") == url]
        for k in keys_to_remove:
            del self._cache[k]

    def clear(self):
        """Clear entire cache."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
