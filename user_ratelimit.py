"""Pry — per-user rate limiting with quota enforcement.

Extends the IP-based rate limiter with user-scoped limits, monthly quotas,
and API key tier awareness.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from db import APIKey, Usage, async_session_scope
from settings import settings


# Tier-based default limits
TIER_LIMITS = {
    "FREE": {"rpm": 60, "quota_monthly": 10_000, "burst": 100},
    "PRO": {"rpm": 300, "quota_monthly": 100_000, "burst": 500},
    "ENTERPRISE": {"rpm": 1200, "quota_monthly": 1_000_000, "burst": 2000},
}


@dataclass
class UserBucket:
    """Token bucket for a specific user/API key."""

    tokens: float
    last_refill: float
    total_requests: int = 0
    blocked_requests: int = 0
    quota_used: int = 0
    quota_reset_at: float = 0.0


class UserRateLimiter:
    """Per-user rate limiter with monthly quota enforcement.

    Features:
    - Token bucket per API key (not IP)
    - Monthly quota tracking with automatic reset
    - Tier-based limits (FREE/PRO/ENTERPRISE)
    - Per-endpoint cost tracking
    - Async DB persistence for quota
    """

    def __init__(self):
        self._buckets: dict[str, UserBucket] = {}
        self._cleanup_interval = 300  # 5 min
        self._last_cleanup = time.time()
        self._quota_sync_interval = 60  # 1 min
        self._last_quota_sync = time.time()

    def _get_limits(self, tier: str) -> dict[str, int]:
        """Get rate limits for a tier."""
        return TIER_LIMITS.get(tier.upper(), TIER_LIMITS["FREE"])

    def _get_quota_reset_timestamp(self) -> float:
        """Get the timestamp for the next monthly quota reset (1st of next month)."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
        else:
            next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
        return next_month.timestamp()

    async def _load_quota_from_db(self, api_key_id: str) -> int:
        """Load current month's quota usage from database."""
        try:
            from datetime import UTC, datetime

            now = datetime.now(UTC)
            month_start = datetime(now.year, now.month, 1, tzinfo=UTC)

            async with async_session_scope() as session:
                from sqlalchemy import func, select

                result = await session.execute(
                    select(func.coalesce(func.sum(Usage.cost_usd), 0))
                    .where(Usage.api_key_id == api_key_id)
                    .where(Usage.created_at >= month_start)
                )
                return int(result.scalar() or 0)
        except Exception:
            return 0

    async def _sync_quota(self, api_key_id: str, bucket: UserBucket) -> None:
        """Sync quota from database periodically."""
        now = time.time()
        if now - self._last_quota_sync > self._quota_sync_interval:
            bucket.quota_used = await self._load_quota_from_db(api_key_id)
            self._last_quota_sync = now

    def check(
        self,
        api_key_id: str,
        tier: str = "FREE",
        rpm: int | None = None,
        quota_monthly: int | None = None,
        cost_usd: float = 0.0,
    ) -> tuple[bool, dict[str, Any]]:
        """Check if request is allowed for this API key.

        Returns (allowed, stats_dict).
        """
        now = time.time()
        limits = self._get_limits(tier)
        rate = rpm if rpm is not None else limits["rpm"]
        quota = quota_monthly if quota_monthly is not None else limits["quota_monthly"]
        burst = limits["burst"]

        # Periodic cleanup of stale buckets
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup(now)

        # Get or create bucket
        if api_key_id not in self._buckets:
            bucket = UserBucket(
                tokens=burst,
                last_refill=now,
                quota_used=0,
                quota_reset_at=self._get_quota_reset_timestamp(),
            )
            self._buckets[api_key_id] = bucket
        else:
            bucket = self._buckets[api_key_id]

        # Check quota reset
        if now >= bucket.quota_reset_at:
            bucket.quota_used = 0
            bucket.quota_reset_at = self._get_quota_reset_timestamp()

        # Refill tokens
        elapsed = now - bucket.last_refill
        bucket.tokens = min(burst, bucket.tokens + elapsed * (rate / 60))
        bucket.last_refill = now

        # Check quota
        if bucket.quota_used + cost_usd > quota:
            bucket.blocked_requests += 1
            return False, {
                "allowed": False,
                "reason": "quota_exceeded",
                "quota_used": bucket.quota_used,
                "quota_limit": quota,
                "quota_reset_at": bucket.quota_reset_at,
                "retry_after": bucket.quota_reset_at - now,
            }

        # Check rate limit
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            bucket.total_requests += 1
            bucket.quota_used += cost_usd
            return True, {
                "allowed": True,
                "remaining": int(bucket.tokens),
                "limit": rate,
                "quota_used": bucket.quota_used,
                "quota_limit": quota,
                "quota_remaining": quota - bucket.quota_used,
                "total": bucket.total_requests,
            }
        else:
            bucket.blocked_requests += 1
            wait_time = (1 - bucket.tokens) * (60 / rate)
            return False, {
                "allowed": False,
                "reason": "rate_limited",
                "remaining": 0,
                "limit": rate,
                "retry_after": round(wait_time, 1),
                "total": bucket.total_requests,
                "blocked": bucket.blocked_requests,
            }

    def _cleanup(self, now: float) -> None:
        """Remove stale buckets older than 1 hour."""
        stale = [key for key, b in self._buckets.items() if now - b.last_refill > 3600]
        for key in stale:
            del self._buckets[key]
        self._last_cleanup = now

    def get_stats(self, api_key_id: str | None = None) -> dict[str, Any]:
        """Get rate limiter statistics."""
        if api_key_id:
            bucket = self._buckets.get(api_key_id)
            if not bucket:
                return {"error": "not_found"}
            limits = self._get_limits("FREE")  # default
            return {
                "api_key_id": api_key_id,
                "remaining": int(bucket.tokens),
                "limit": limits["rpm"],
                "quota_used": bucket.quota_used,
                "quota_limit": limits["quota_monthly"],
                "total_requests": bucket.total_requests,
                "blocked_requests": bucket.blocked_requests,
            }
        else:
            total_active = len(self._buckets)
            total_blocked = sum(b.blocked_requests for b in self._buckets.values())
            total_requests = sum(b.total_requests for b in self._buckets.values())
            return {
                "active_keys": total_active,
                "total_requests": total_requests,
                "total_blocked": total_blocked,
            }

    async def record_usage(
        self,
        api_key_id: str,
        user_id: str,
        operation: str,
        endpoint: str,
        status: str,
        duration_ms: int,
        bytes_in: int,
        bytes_out: int,
        cost_usd: float,
        ip: str = "",
        user_agent: str = "",
        error_message: str = "",
    ) -> None:
        """Record usage to database for billing/analytics."""
        try:
            async with async_session_scope() as session:
                usage = Usage(
                    user_id=user_id,
                    api_key_id=api_key_id,
                    operation=operation,
                    endpoint=endpoint,
                    status=status,
                    duration_ms=duration_ms,
                    bytes_in=bytes_in,
                    bytes_out=bytes_out,
                    cost_usd=cost_usd,
                    ip=ip,
                    user_agent=user_agent,
                    error_message=error_message,
                )
                session.add(usage)
        except Exception:
            pass  # Never let usage recording break the request


# Global instance
user_ratelimiter = UserRateLimiter()
