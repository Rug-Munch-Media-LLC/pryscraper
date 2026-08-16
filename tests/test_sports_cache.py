# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for sports_data.cache — TTL cache + token-bucket rate limiter.

Covers TTL expiry, bounded LRU/expired eviction, thread safety, the async
aliases, token-bucket burst/refill/monthly-cap behaviour, and the sports
settings defaults + env overrides. All timing uses an injectable fake clock
(no real sleeps).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from settings import PrySettings, settings
from sports_data import cache as cache_mod
from sports_data.cache import TokenBucketRateLimiter, TTLCache


class FakeClock:
    """Deterministic clock for expiry/refill tests."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


# ── TTLCache: basic get/set ─────────────────────────────────────────────


def test_ttl_set_get_roundtrip() -> None:
    clock = FakeClock()
    cache = TTLCache(default_ttl=10.0, clock=clock)
    cache.set("odds:nba", {"home": 1.85})
    assert cache.get("odds:nba") == {"home": 1.85}


def test_ttl_missing_returns_none() -> None:
    cache = TTLCache()
    assert cache.get("missing") is None


def test_ttl_tuple_keys() -> None:
    cache = TTLCache()
    cache.set(("odds", "nba", "us"), [1, 2, 3])
    assert cache.get(("odds", "nba", "us")) == [1, 2, 3]


def test_ttl_delete() -> None:
    cache = TTLCache()
    cache.set("k", "v")
    assert cache.delete("k") is True
    assert cache.delete("k") is False
    assert cache.get("k") is None


# ── TTLCache: expiry ────────────────────────────────────────────────────


def test_ttl_expiry_after_ttl_seconds() -> None:
    clock = FakeClock()
    cache = TTLCache(default_ttl=10.0, clock=clock)
    cache.set("k", "v")
    clock.advance(9.5)
    assert cache.get("k") == "v"
    clock.advance(0.6)  # now 10.1s elapsed
    assert cache.get("k") is None


def test_ttl_expired_entry_removed_and_counted_as_miss() -> None:
    clock = FakeClock()
    cache = TTLCache(default_ttl=10.0, clock=clock)
    cache.set("k", "v")
    clock.advance(11.0)
    cache.get("k")
    assert cache.stats()["size"] == 0
    assert cache.stats()["hits"] == 0
    assert cache.stats()["misses"] == 1


def test_ttl_per_entry_ttl_override() -> None:
    clock = FakeClock()
    cache = TTLCache(default_ttl=60.0, clock=clock)
    cache.set("short", "v", ttl=2.0)
    cache.set("long", "w")
    clock.advance(3.0)
    assert cache.get("short") is None
    assert cache.get("long") == "w"


def test_ttl_none_disables_expiry() -> None:
    clock = FakeClock()
    cache = TTLCache(default_ttl=None, clock=clock)
    cache.set("k", "v")
    clock.advance(3600.0)
    assert cache.get("k") == "v"


# ── TTLCache: bounded capacity / eviction ───────────────────────────────


def test_ttl_bounded_lru_eviction() -> None:
    clock = FakeClock()
    cache = TTLCache(capacity=2, default_ttl=None, clock=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # refresh a -> LRU order is b, a
    cache.set("c", 3)  # at capacity -> evict b
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_ttl_evicts_expired_before_capacity() -> None:
    clock = FakeClock()
    cache = TTLCache(capacity=2, default_ttl=10.0, clock=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    clock.advance(11.0)  # both expired
    cache.set("c", 3)  # purges expired a+b first
    assert cache.get("a") is None
    assert cache.get("b") is None
    assert cache.get("c") == 3
    assert cache.stats()["size"] == 1


def test_ttl_clear_resets_state() -> None:
    cache = TTLCache()
    cache.set("a", 1)
    cache.get("a")
    cache.clear()
    stats = cache.stats()
    assert stats["size"] == 0
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert cache.get("a") is None


# ── TTLCache: thread safety ─────────────────────────────────────────────


def test_ttl_thread_safety_counts() -> None:
    cache = TTLCache(capacity=4096, default_ttl=3600.0)
    n_threads = 8
    n_items = 200
    total_gets = n_threads * n_items

    def worker(worker_id: int) -> None:
        for i in range(n_items):
            key = f"w{worker_id}-{i}"
            cache.set(key, i)
            cache.get(key)

    threads = [Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stats = cache.stats()
    # Every set was followed by exactly one successful get (no expiry,
    # capacity 4096 > 1600 entries), so hits == total_gets and misses == 0.
    assert stats["hits"] == total_gets
    assert stats["misses"] == 0
    assert stats["size"] == total_gets


# ── TTLCache: async aliases ─────────────────────────────────────────────


def test_ttl_async_aliases() -> None:
    clock = FakeClock()
    cache = TTLCache(default_ttl=10.0, clock=clock)

    async def run() -> None:
        await cache.aset("k", {"odds": 1.85})
        assert await cache.aget("k") == {"odds": 1.85}
        await cache.aclear()
        assert await cache.aget("k") is None

    asyncio.run(run())


# ── TTLCache: validation ────────────────────────────────────────────────


def test_ttl_invalid_constructor_args() -> None:
    with pytest.raises(ValueError, match="capacity"):
        TTLCache(capacity=0)
    with pytest.raises(ValueError, match="default_ttl"):
        TTLCache(default_ttl=0.0)
    with pytest.raises(ValueError, match="default_ttl"):
        TTLCache(default_ttl=-5.0)


def test_ttl_invalid_set_ttl() -> None:
    cache = TTLCache()
    with pytest.raises(ValueError, match="ttl"):
        cache.set("k", "v", ttl=0)


# ── TokenBucketRateLimiter: burst / refill / quota ──────────────────────


def test_rate_limiter_burst_then_deny() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60.0, burst=10, clock=clock)
    for _ in range(10):
        assert limiter.acquire() is True
    assert limiter.acquire() is False
    assert limiter.wait_seconds() > 0.0


def test_rate_limiter_refills_over_time() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60.0, burst=10, clock=clock)
    for _ in range(10):
        assert limiter.acquire() is True
    clock.advance(5.0)  # 60/min -> 5 tokens in 5s
    for _ in range(5):
        assert limiter.acquire() is True
    assert limiter.acquire() is False


def test_rate_limiter_wait_seconds() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60.0, burst=1, clock=clock)
    assert limiter.acquire() is True
    assert limiter.wait_seconds() == pytest.approx(1.0)
    clock.advance(0.5)
    assert limiter.wait_seconds() == pytest.approx(0.5)
    clock.advance(0.5)
    assert limiter.wait_seconds() == 0.0


def test_rate_limiter_default_burst_equals_rpm() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=30.0, clock=clock)
    assert limiter.burst == 30.0
    for _ in range(30):
        assert limiter.acquire() is True
    assert limiter.acquire() is False


def test_rate_limiter_monthly_quota_is_hard() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60.0, burst=10, monthly_limit=3, clock=clock)
    for _ in range(3):
        assert limiter.acquire() is True
    assert limiter.total_consumed == 3
    clock.advance(600.0)  # tokens refill, but the monthly cap is a hard wall
    assert limiter.acquire() is False
    assert limiter.wait_seconds() == float("inf")


def test_rate_limiter_remaining_property() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60.0, burst=10, clock=clock)
    assert limiter.remaining == pytest.approx(10.0)
    assert limiter.acquire() is True
    assert limiter.remaining == pytest.approx(9.0)


def test_rate_limiter_invalid_args() -> None:
    with pytest.raises(ValueError, match="rate_per_minute"):
        TokenBucketRateLimiter(rate_per_minute=0)
    with pytest.raises(ValueError, match="burst"):
        TokenBucketRateLimiter(rate_per_minute=30.0, burst=0)
    with pytest.raises(ValueError, match="monthly_limit"):
        TokenBucketRateLimiter(rate_per_minute=30.0, monthly_limit=0)
    limiter = TokenBucketRateLimiter(rate_per_minute=30.0)
    with pytest.raises(ValueError, match="tokens"):
        limiter.acquire(0)
    with pytest.raises(ValueError, match="tokens"):
        limiter.wait_seconds(-1)


# ── Settings integration ────────────────────────────────────────────────


def test_settings_sports_defaults(tmp_path: Path) -> None:
    s = PrySettings(config_file=tmp_path / "config.json")
    assert s.odds_api_key == ""
    assert s.sports_odds_cache_ttl_seconds == 10
    assert s.sports_odds_rate_limit_rpm == 30


def test_settings_sports_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test_odds_key_123")
    monkeypatch.setenv("PRY_SPORTS_ODDS_CACHE_TTL_SECONDS", "25")
    monkeypatch.setenv("PRY_SPORTS_ODDS_RATE_LIMIT_RPM", "60")
    s = PrySettings(config_file=tmp_path / "config.json")
    assert s.odds_api_key == "test_odds_key_123"
    assert s.sports_odds_cache_ttl_seconds == 25
    assert s.sports_odds_rate_limit_rpm == 60


def test_singletons_wired_to_settings() -> None:
    assert cache_mod.rate_limiter.rate_per_minute == settings.sports_odds_rate_limit_rpm
    assert cache_mod.rate_limiter.monthly_limit == 500
    assert cache_mod.get_default_cache() is cache_mod.get_default_cache()
    assert cache_mod.get_default_cache().default_ttl == settings.sports_odds_cache_ttl_seconds


# ── Import guard (parallel-agent safety) ────────────────────────────────


def test_cache_module_is_self_contained() -> None:
    """cache.py must never import sibling sports_data modules."""
    src = Path(cache_mod.__file__).read_text(encoding="utf-8")
    assert "import sports_data" not in src
    assert "from sports_data" not in src


def test_sports_package_re_exports_cache_helpers() -> None:
    """The package __init__ dynamic loop must surface the cache helpers."""
    import sports_data

    # getattr(..., None): mypy cannot see the package's runtime re-export
    # loop, and B009 only permits getattr when a default is supplied.
    assert getattr(sports_data, "TTLCache", None) is TTLCache
    assert getattr(sports_data, "TokenBucketRateLimiter", None) is TokenBucketRateLimiter
    assert callable(getattr(sports_data, "get_default_cache", None))


def test_sports_cache_helpers_exist() -> None:
    """Compile-time smoke check of the public surface used by siblings."""
    _: Any = cache_mod.rate_limiter
    _ = cache_mod.get_default_cache()
    cache = TTLCache()
    cache.set("k", 1)
    assert cache.get("k") == 1
