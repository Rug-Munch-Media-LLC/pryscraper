# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for user_ratelimit.py — quota accounting, stats and cleanup."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from pry.core.user_ratelimit import TIER_LIMITS, UserBucket, UserRateLimiter


@pytest.fixture
def limiter() -> UserRateLimiter:
    """Return a fresh UserRateLimiter with no buckets."""
    return UserRateLimiter()


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
# PRO & ENTERPRISE tier (rpm surface)
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


# Tier table sanity — the numbers other tiers are compared against.
def test_get_limits_free():
    assert TIER_LIMITS["FREE"]["rpm"] == 60
    assert TIER_LIMITS["FREE"]["quota_monthly"] == 10_000


def test_get_limits_pro():
    assert TIER_LIMITS["PRO"]["rpm"] == 300
    assert TIER_LIMITS["PRO"]["quota_monthly"] == 100_000


def test_get_limits_enterprise():
    assert TIER_LIMITS["ENTERPRISE"]["rpm"] == 1_200
    assert TIER_LIMITS["ENTERPRISE"]["quota_monthly"] == 1_000_000
