"""In-memory TTL cache + token-bucket rate limiter shared by sports_data.

Every module in the sports_data package (odds, scores, stats) uses these
helpers so betting bots that poll sub-minute get sub-100ms reads while the
upstream free APIs (The Odds API free tier = 500 requests/month) are not
hammered:

* :class:`TTLCache` — small, thread-safe, bounded in-memory cache with TTL
  expiry. ``get`` / ``set`` / ``clear`` are O(1), non-blocking and safe to
  call from async code (no I/O, sub-microsecond lock hold). Await-style
  callers get the ``aget`` / ``aset`` / ``aclear`` aliases.
* :class:`TokenBucketRateLimiter` — thread-safe token bucket enforcing a
  sustained requests-per-minute budget plus an optional hard monthly cap.
* :data:`rate_limiter` — shared singleton wired to the
  ``sports_odds_rate_limit_rpm`` setting (default 30) with the Odds API
  free-tier monthly cap (500).

This module is intentionally dependency-free beyond the stdlib and
``settings``: it never imports sibling sports_data modules, so it loads
cleanly in parallel-agent development and from any consumer.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from settings import settings

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable

# The Odds API free tier: 500 requests/month (see sports_data/odds.py).
_ODDS_API_MONTHLY_QUOTA = 500

# Default max entries for the shared cache — one key per (sport, region,
# market) lookup is far below this in practice.
_DEFAULT_CACHE_CAPACITY = 256


class TTLCache:
    """Thread-safe, bounded in-memory cache with TTL expiry.

    Entries expire lazily: stale values are dropped on access (``get`` /
    ``set``). When the cache is at capacity, expired entries are purged
    first, then least-recently-used entries are evicted.

    Every method is non-blocking and holds the internal lock for
    microseconds, so calling them from async code is safe. Await-style
    callers can use the ``aget`` / ``aset`` / ``aclear`` aliases.
    """

    def __init__(
        self,
        capacity: int = _DEFAULT_CACHE_CAPACITY,
        default_ttl: float | None = 10.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Initialize the cache.

        Args:
            capacity: Max entries before LRU eviction (must be >= 1).
            default_ttl: Seconds until entries expire; ``None`` disables
                time-based expiry (capacity eviction still applies).
            clock: Callable returning the current time in seconds
                (``time.monotonic`` by default); injectable for
                deterministic tests.
        """
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if default_ttl is not None and default_ttl <= 0:
            raise ValueError("default_ttl must be > 0 or None")
        self.capacity = capacity
        self.default_ttl = default_ttl
        self._clock: Callable[[], float] = clock or time.monotonic
        self._data: OrderedDict[Hashable, tuple[float | None, Any]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: Hashable) -> Any | None:
        """Return the cached value for ``key``, or ``None`` if missing/expired."""
        now = self._clock()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires, value = entry
            if expires is not None and expires <= now:
                del self._data[key]
                self._misses += 1
                return None
            self._hits += 1
            self._data.move_to_end(key)
            return value

    def set(self, key: Hashable, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` for ``key``.

        Args:
            key: Any hashable key (e.g. ``("odds", "nba", "us")``).
            value: Value to cache.
            ttl: Seconds until expiry. ``None`` (the default) uses the
                constructor's ``default_ttl``, which itself may be ``None``
                for entries that never expire on their own.
        """
        if ttl is None:
            ttl = self.default_ttl
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be > 0 or None")
        now = self._clock()
        expires = now + ttl if ttl is not None else None
        with self._lock:
            self._data[key] = (expires, value)
            self._data.move_to_end(key)
            self._evict_locked(now)

    def delete(self, key: Hashable) -> bool:
        """Remove ``key``; return True if it existed."""
        with self._lock:
            return self._data.pop(key, None) is not None

    def clear(self) -> None:
        """Remove all entries and reset hit/miss counters."""
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, int | float]:
        """Return size, capacity, hits, misses and hit rate."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._data),
                "capacity": self.capacity,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total * 100, 1) if total else 0.0,
            }

    def _evict_locked(self, now: float) -> None:
        """Drop expired entries, then LRU-evict until under capacity.

        Caller must hold ``self._lock``.
        """
        expired = [
            key
            for key, (expires, _value) in self._data.items()
            if expires is not None and expires <= now
        ]
        for key in expired:
            del self._data[key]
        while len(self._data) > self.capacity:
            self._data.popitem(last=False)

    # ── Async aliases (await-style callers) ──────────────────────────────

    async def aget(self, key: Hashable) -> Any | None:
        """Async alias for :meth:`get` (never blocks)."""
        return self.get(key)

    async def aset(self, key: Hashable, value: Any, ttl: float | None = None) -> None:
        """Async alias for :meth:`set` (never blocks)."""
        self.set(key, value, ttl)

    async def aclear(self) -> None:
        """Async alias for :meth:`clear` (never blocks)."""
        self.clear()


class TokenBucketRateLimiter:
    """Thread-safe token bucket for upstream request budgets.

    The bucket refills continuously at ``rate_per_minute`` tokens per
    minute up to ``burst`` capacity, so short bursts are allowed while the
    sustained rate stays bounded. An optional ``monthly_limit`` enforces a
    hard cap on total tokens ever consumed (e.g. the Odds API free tier's
    500 requests/month); once reached, :meth:`acquire` always returns
    ``False`` and :meth:`wait_seconds` returns infinity.

    Non-blocking by design — callers poll with ``acquire()`` and back off
    by ``wait_seconds()`` when it returns ``False`` (for async code:
    ``await asyncio.sleep(limiter.wait_seconds())``).
    """

    def __init__(
        self,
        rate_per_minute: float = 30.0,
        burst: int | None = None,
        monthly_limit: int | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Initialize the limiter.

        Args:
            rate_per_minute: Sustained token refill rate (requests/min).
            burst: Max token capacity (max immediate burst). Defaults to
                ``rate_per_minute`` (e.g. 30 immediate requests then
                steady 30/min refill).
            monthly_limit: Hard cap on total tokens ever consumed; ``None``
                disables the cap (e.g. paid Odds API plans).
            clock: Callable returning current time in seconds
                (``time.monotonic`` by default); injectable for tests.
        """
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be > 0")
        if burst is not None and burst <= 0:
            raise ValueError("burst must be > 0")
        if monthly_limit is not None and monthly_limit <= 0:
            raise ValueError("monthly_limit must be > 0")
        self.rate_per_minute = float(rate_per_minute)
        self.burst = float(burst) if burst is not None else self.rate_per_minute
        self.monthly_limit = monthly_limit
        self._clock: Callable[[], float] = clock or time.monotonic
        self._tokens = self.burst
        self._last_refill = self._clock()
        self._total_consumed = 0.0
        self._lock = threading.RLock()

    def _refill_locked(self, now: float) -> None:
        """Accumulate tokens earned since the last refill (caller holds lock)."""
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self.burst, self._tokens + elapsed * (self.rate_per_minute / 60.0))
        self._last_refill = now

    def acquire(self, tokens: float = 1.0) -> bool:
        """Try to consume ``tokens`` without blocking; False if unavailable."""
        if tokens <= 0:
            raise ValueError("tokens must be > 0")
        with self._lock:
            now = self._clock()
            self._refill_locked(now)
            if (
                self.monthly_limit is not None
                and self._total_consumed + tokens > self.monthly_limit
            ):
                return False
            if self._tokens >= tokens:
                self._tokens -= tokens
                self._total_consumed += tokens
                return True
            return False

    def wait_seconds(self, tokens: float = 1.0) -> float:
        """Seconds until ``tokens`` would be available (0 if available now).

        Returns infinity when the ``monthly_limit`` has been exhausted.
        """
        if tokens <= 0:
            raise ValueError("tokens must be > 0")
        with self._lock:
            now = self._clock()
            self._refill_locked(now)
            if (
                self.monthly_limit is not None
                and self._total_consumed + tokens > self.monthly_limit
            ):
                return float("inf")
            if self._tokens >= tokens:
                return 0.0
            needed = tokens - self._tokens
            return needed / (self.rate_per_minute / 60.0)

    @property
    def remaining(self) -> float:
        """Tokens available right now (after refill)."""
        with self._lock:
            now = self._clock()
            self._refill_locked(now)
            return self._tokens

    @property
    def total_consumed(self) -> float:
        """Total tokens consumed since creation (for monthly budget checks)."""
        return self._total_consumed


# Shared singleton wired to settings. Bots on paid Odds API plans can build
# their own limiter without a monthly cap — paid calls have no rate-limit
# wall (see .env.example "ready for any bot" note).
rate_limiter = TokenBucketRateLimiter(
    rate_per_minute=settings.sports_odds_rate_limit_rpm,
    monthly_limit=_ODDS_API_MONTHLY_QUOTA,
)

_default_cache: TTLCache | None = None


def get_default_cache() -> TTLCache:
    """Return the shared sports-data cache (lazily created, settings-backed)."""
    global _default_cache
    if _default_cache is None:
        _default_cache = TTLCache(
            capacity=_DEFAULT_CACHE_CAPACITY,
            default_ttl=settings.sports_odds_cache_ttl_seconds,
        )
    return _default_cache
