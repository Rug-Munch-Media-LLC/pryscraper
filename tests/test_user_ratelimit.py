# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for user_ratelimit.py — per-user rate limiting with quota enforcement."""

from __future__ import annotations

import time
from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest

from pry.core import user_ratelimit as user_ratelimit_mod
from pry.core.user_ratelimit import (
    TIER_LIMITS,
    QuotaUnavailableError,
    UserBucket,
    UserRateLimiter,
)


@pytest.fixture
def limiter() -> UserRateLimiter:
    """Return a fresh UserRateLimiter with no buckets."""
    return UserRateLimiter()


# ---------------------------------------------------------------------------
# Bucket creation & defaults
# ---------------------------------------------------------------------------


def test_limiter_init(limiter: UserRateLimiter) -> None:
    assert limiter._buckets == {}
    assert limiter._cleanup_interval == 300
    assert limiter._last_cleanup > 0


def test_get_limits_free():
    assert TIER_LIMITS["FREE"]["rpm"] == 60
    assert TIER_LIMITS["FREE"]["quota_monthly"] == 10_000


def test_get_limits_pro():
    assert TIER_LIMITS["PRO"]["rpm"] == 300
    assert TIER_LIMITS["PRO"]["quota_monthly"] == 100_000


def test_get_limits_enterprise():
    assert TIER_LIMITS["ENTERPRISE"]["rpm"] == 1_200
    assert TIER_LIMITS["ENTERPRISE"]["quota_monthly"] == 1_000_000


def test_get_limits_unknown_falls_back_to_free(limiter: UserRateLimiter):
    limits = limiter._get_limits("UNKNOWN_TIER")
    assert limits == TIER_LIMITS["FREE"]


def test_get_limits_case_insensitive(limiter: UserRateLimiter):
    limits = limiter._get_limits("pro")
    assert limits["rpm"] == 300
    limits2 = limiter._get_limits("Enterprise")
    assert limits2["rpm"] == 1_200


# ---------------------------------------------------------------------------
# Quota reset timestamp
# ---------------------------------------------------------------------------


def test_quota_reset_timestamp_future(limiter: UserRateLimiter):
    """Returns a timestamp in the future (next month's 1st)."""
    import time
    from datetime import UTC, datetime

    datetime.now(UTC)
    ts = limiter._get_quota_reset_timestamp()
    now_ts = time.time()
    # Should be in the future
    assert ts > now_ts, "Quota reset should be in the future"
    # Should be before the month after next (at most 62 days out)
    assert ts < now_ts + 62 * 86400, "Quota reset should be next month's 1st"


def test_quota_reset_timestamp_is_first_of_month(limiter: UserRateLimiter):
    """Quota reset timestamp should always be the 1st of a month."""
    from datetime import datetime

    ts = limiter._get_quota_reset_timestamp()
    dt = datetime.fromtimestamp(ts, tz=UTC)
    assert dt.day == 1, f"Quota reset should be the 1st, got day {dt.day}"
    assert dt.hour == 0
    assert dt.minute == 0


# ---------------------------------------------------------------------------
# Basic rate limit checks — FREE tier
# ---------------------------------------------------------------------------


def test_check_first_request_allowed(limiter: UserRateLimiter):
    allowed, info = limiter.check("key1", tier="FREE")
    assert allowed is True
    assert info["allowed"] is True
    assert info["remaining"] >= 0
    assert "limit" in info
    assert info["quota_limit"] == 10_000


def test_check_rejects_when_quota_exceeded(limiter: UserRateLimiter):
    """Exceeding monthly quota should block."""
    with patch.object(limiter, "_get_quota_reset_timestamp", return_value=time.time() + 3600):
        allowed, info = limiter.check("key2", tier="FREE", quota_monthly=0, cost_usd=1)
        assert allowed is False
        assert info["reason"] == "quota_exceeded"


def test_check_rejects_when_rate_limited(limiter: UserRateLimiter):
    """Exhausting tokens should block with rate_limited."""
    # Use FREE tier (60 rpm / 1 token per sec). Drain tokens by setting burst=1, rpm=1
    with patch.object(
        limiter, "_get_limits", return_value={"rpm": 1, "quota_monthly": 999999, "burst": 1}
    ):
        allowed, _info = limiter.check("key3", tier="FREE")
        assert allowed is True

        # Second request should be rate-limited (no tokens, low refill rate)
        allowed2, info2 = limiter.check("key3", tier="FREE")
        assert allowed2 is False
        assert info2["reason"] == "rate_limited"


def test_check_bucket_created_on_first_use(limiter: UserRateLimiter):
    assert "new_key" not in limiter._buckets
    limiter.check("new_key", tier="PRO")
    assert "new_key" in limiter._buckets
    bucket = limiter._buckets["new_key"]
    assert isinstance(bucket, UserBucket)
    assert bucket.total_requests == 1
    assert bucket.tokens < TIER_LIMITS["PRO"]["burst"]  # one token consumed


# ---------------------------------------------------------------------------
# PRO & ENTERPRISE tier
# ---------------------------------------------------------------------------


def test_pro_tier_limits(limiter: UserRateLimiter):
    allowed, info = limiter.check("pro_key", tier="PRO")
    assert allowed is True
    # PRO has higher burst + rpm
    assert info["limit"] == 300


def test_enterprise_tier_limits(limiter: UserRateLimiter):
    allowed, info = limiter.check("ent_key", tier="ENTERPRISE")
    assert allowed is True
    assert info["limit"] == 1_200


# ---------------------------------------------------------------------------
# Quota tracking
# ---------------------------------------------------------------------------


def test_quota_consumed_on_allowed_request(limiter: UserRateLimiter):
    with patch.object(limiter, "_get_quota_reset_timestamp", return_value=time.time() + 3600):
        allowed, info = limiter.check("q_key", tier="FREE", cost_usd=50)
        assert allowed is True
        assert info["quota_used"] == 50
        assert info["quota_remaining"] == 10_000 - 50


def test_quota_reset_on_new_month(limiter: UserRateLimiter):
    bucket = UserBucket(
        tokens=100,
        last_refill=time.time(),
        quota_used=9_500,
        quota_reset_at=time.time() - 1,  # expired
    )
    limiter._buckets["month_key"] = bucket
    with patch.object(limiter, "_get_quota_reset_timestamp", return_value=time.time() + 3600):
        allowed, info = limiter.check("month_key", tier="FREE", cost_usd=100)
        assert allowed is True
        # Quota was reset because reset_at was in the past
        assert info["quota_used"] == 100
        assert info["quota_remaining"] == 10_000 - 100


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_stats_for_existing_key(limiter: UserRateLimiter):
    limiter.check("stats_key")
    stats = limiter.get_stats("stats_key")
    assert stats["api_key_id"] == "stats_key"
    assert stats["total_requests"] == 1
    assert stats["remaining"] >= 0
    assert stats["limit"] == 60


def test_stats_for_missing_key(limiter: UserRateLimiter):
    stats = limiter.get_stats("nonexistent")
    assert stats == {"error": "not_found"}


def test_stats_global(limiter: UserRateLimiter):
    limiter.check("global1")
    limiter.check("global2")
    stats = limiter.get_stats()
    assert stats["active_keys"] == 2
    assert stats["total_requests"] == 2


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_cleanup_removes_stale_buckets(limiter: UserRateLimiter):
    now = time.time()
    old_bucket = UserBucket(tokens=100, last_refill=now - 4000)
    limiter._buckets["old_key"] = old_bucket
    limiter._buckets["fresh_key"] = UserBucket(tokens=100, last_refill=now - 100)
    limiter._cleanup(now)
    assert "old_key" not in limiter._buckets
    assert "fresh_key" in limiter._buckets


# ---------------------------------------------------------------------------
# Record usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_usage_database_write(limiter: UserRateLimiter):
    """record_usage should write a Usage record to the DB."""
    with patch("pry.core.user_ratelimit.async_session_scope") as mock_scope:
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_scope.return_value = mock_session

        await limiter.record_usage(
            api_key_id="key1",
            user_id="user1",
            operation="test",
            endpoint="/v1/prompt",
            status="success",
            duration_ms=100,
            bytes_in=50,
            bytes_out=200,
            cost_usd=0.01,
        )

        mock_session.add.assert_called_once()
        added = mock_session.add.call_args[0][0]
        assert added.api_key_id == "key1"
        assert added.user_id == "user1"
        assert added.operation == "test"
        assert added.status == "success"


@pytest.mark.asyncio
async def test_record_usage_does_not_raise_on_db_failure(limiter: UserRateLimiter):
    """record_usage should never raise — errors are swallowed."""
    with patch("pry.core.user_ratelimit.async_session_scope", side_effect=RuntimeError("DB down")):
        # Should not raise
        await limiter.record_usage(
            api_key_id="key1",
            user_id="user1",
            operation="test",
            endpoint="/v1/prompt",
            status="success",
            duration_ms=100,
            bytes_in=50,
            bytes_out=200,
            cost_usd=0.01,
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_multiple_requests_increments_counters(limiter: UserRateLimiter):
    for _ in range(5):
        limiter.check("multi_key")
    assert limiter._buckets["multi_key"].total_requests == 5


def test_cost_usd_accumulates(limiter: UserRateLimiter):
    with patch.object(limiter, "_get_quota_reset_timestamp", return_value=time.time() + 3600):
        info: dict = {}
        for _i in range(3):
            allowed, info = limiter.check("cost_key", tier="FREE", cost_usd=10.0)
            assert allowed is True
        assert info["quota_used"] == 30.0


def test_overflow_burst_allowed(limiter: UserRateLimiter):
    """With large burst, many requests should succeed."""
    with patch.object(
        limiter, "_get_limits", return_value={"rpm": 9999, "quota_monthly": 999999, "burst": 1000}
    ):
        for i in range(100):
            allowed, _ = limiter.check("burst_key")
            assert allowed is True, f"Request {i + 1} should be allowed"


# ---------------------------------------------------------------------------
# Fail-closed quota reads (DB outage must not read as an unlimited user)
# ---------------------------------------------------------------------------


async def test_db_outage_does_not_report_zero_quota(limiter: UserRateLimiter):
    """A SQLAlchemyError must deny, not silently return quota_used=0.

    Returning 0 makes every user look like they have an UNLIMITED quota, so a
    database outage would disable quota enforcement entirely. The read must
    raise QuotaUnavailableError, and the check must deny explicitly.
    """
    from sqlalchemy.exc import OperationalError

    db_error = OperationalError("SELECT sum(cost_usd)...", {}, Exception("connection refused"))

    class _FailingSession:
        async def __aenter__(self):
            raise db_error

        async def __aexit__(self, *exc):
            return False

    def _scope():
        return _FailingSession()

    real_scope = user_ratelimit_mod.async_session_scope
    user_ratelimit_mod.async_session_scope = _scope
    try:
        # 1. The DB read itself denies instead of returning 0.
        with pytest.raises(QuotaUnavailableError):
            await limiter._load_quota_from_db("api_key_db_down")

        # 2. The sync path marks the bucket unverified; it does NOT zero it.
        bucket = UserBucket(tokens=100, last_refill=time.time(), quota_used=500.0)
        limiter._buckets["api_key_db_down"] = bucket
        bucket.quota_synced_at = time.time() - limiter.quota_ttl - 1  # force stale
        await limiter._sync_quota("api_key_db_down", bucket)
        assert bucket.quota_unverified is True
        assert bucket.quota_used == 500.0, "known usage must not be reset to zero"

        # 3. check() denies explicitly rather than admitting the request.
        allowed, info = limiter.check("api_key_db_down", tier="FREE", cost_usd=1.0)
        assert allowed is False
        assert info["reason"] == "quota_unavailable"
        # The denial reports no usage at all — never a fabricated zero.
        assert "quota_used" not in info
    finally:
        user_ratelimit_mod.async_session_scope = real_scope
