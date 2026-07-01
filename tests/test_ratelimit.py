from ratelimit import RateLimiter


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
