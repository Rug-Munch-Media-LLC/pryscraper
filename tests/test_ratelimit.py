# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from pry.core.ratelimit import RateLimiter


def test_rate_limiter_allows_first_request() -> None:
    rl = RateLimiter(default_rpm=60, burst=10)
    allowed, stats = rl.check("127.0.0.1")
    assert allowed is True
    assert stats["remaining"] >= 0


def test_rate_limiter_tracks_total() -> None:
    rl = RateLimiter(default_rpm=1000, burst=100)
    for _ in range(5):
        rl.check("127.0.0.1")
    stats = rl.get_stats()
    assert stats["total_requests"] >= 5
    assert stats["active_ips"] >= 1


def test_rate_limiter_blocks_excessive_burst() -> None:
    rl = RateLimiter(default_rpm=1, burst=1)
    rl.check("127.0.0.1")
    allowed, stats = rl.check("127.0.0.1")
    assert allowed is False
    assert stats["retry_after"] > 0


def test_rate_limiter_multiple_ips() -> None:
    rl = RateLimiter(default_rpm=100, burst=10)
    rl.check("1.1.1.1")
    rl.check("2.2.2.2")
    rl.check("3.3.3.3")
    stats = rl.get_stats()
    assert stats["active_ips"] == 3


def test_rate_limiter_cleanup() -> None:
    rl = RateLimiter(default_rpm=60, burst=10)
    rl._buckets["stale_ip"] = {"tokens": 10, "last_refill": 0, "total": 0, "blocked": 0}
    rl._cleanup()
    assert "stale_ip" not in rl._buckets


def test_rate_limiter_get_stats_shape() -> None:
    rl = RateLimiter(default_rpm=120, burst=200)
    rl.check("test_ip")
    stats = rl.get_stats()
    assert "active_ips" in stats
    assert "total_requests" in stats
    assert "total_blocked" in stats
    assert "default_rpm" in stats
    assert stats["default_rpm"] == 120


# ---------------------------------------------------------------------------
# Redis backend (fail-open availability, fail-closed correctness)
# ---------------------------------------------------------------------------


class _FakeScript:
    """Mimics a registered Lua script: atomic INCR + EXPIRE-on-first."""

    def __init__(self, store: dict, fail: bool = False) -> None:
        self._store = store
        self._fail = fail

    def __call__(self, keys=None, args=None):
        if self._fail:
            raise ConnectionError("redis down mid-script")
        key = keys[0]
        count = self._store.get(key, 0) + 1
        self._store[key] = count
        return count


class _FakeRedis:
    """Minimal redis double: register_script (atomic INCR+EXPIRE) + PING."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.fail = False

    def ping(self) -> bool:
        if self.fail:
            raise ConnectionError("redis down")
        return True

    def register_script(self, script: str):
        return _FakeScript(self.store, fail=self.fail)


def test_redis_backend_shared_counter_limits_across_instances() -> None:
    fake = _FakeRedis()
    rl_a = RateLimiter(default_rpm=3, burst=100, redis_url="redis://test")
    rl_b = RateLimiter(default_rpm=3, burst=100, redis_url="redis://test")
    rl_a._redis = fake  # inject double, skip real connection
    rl_b._redis = fake

    results = [rl_b.check("9.9.9.9")[0] for _ in range(5)]
    # Shared window of 3 across BOTH limiter instances (multi-replica sim).
    assert results == [True, True, True, False, False]
    assert rl_b.backend == "redis"


def test_redis_stats_shape_and_remaining() -> None:
    fake = _FakeRedis()
    rl = RateLimiter(default_rpm=5, burst=100, redis_url="redis://test")
    rl._redis = fake
    allowed, stats = rl.check("8.8.8.8")
    assert allowed is True
    assert stats["limit"] == 5
    assert stats["remaining"] == 4
    assert "window_reset" in stats


def test_redis_failure_falls_back_to_memory() -> None:
    rl = RateLimiter(default_rpm=60, burst=10, redis_url="redis://test")
    broken = _FakeRedis()
    broken.fail = True
    rl._redis = broken
    allowed, stats = rl.check("7.7.7.7")
    assert allowed is True  # degraded, not down
    assert rl.backend == "memory"
    assert stats["total"] == 1  # memory token-bucket stats shape


def test_no_redis_url_uses_memory() -> None:
    rl = RateLimiter(default_rpm=60, burst=10)
    allowed, _ = rl.check("6.6.6.6")
    assert allowed is True
    assert rl.backend == "memory"


def test_get_stats_reports_backend() -> None:
    rl = RateLimiter(default_rpm=60, burst=10)
    rl.check("5.5.5.5")
    assert rl.get_stats()["backend"] == "memory"
