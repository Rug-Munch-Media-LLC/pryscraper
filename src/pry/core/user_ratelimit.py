"""Pry — per-user rate limiting with quota enforcement.

Extends the IP-based rate limiter with user-scoped limits, monthly quotas,
and API key tier awareness.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
import time
from typing import Any

from pry.core import user_ratelimit_quota, user_ratelimit_stats
from pry.core.db import async_session_scope
from pry.core.user_ratelimit_types import (
    TIER_LIMITS,
    QuotaUnavailableError,
    UserBucket,
)

logger = logging.getLogger(__name__)

# Re-exported so the historical patch point ``pry.core.user_ratelimit.
# async_session_scope`` keeps governing every database access, including the
# ones ``user_ratelimit_quota`` makes (it resolves the name through this
# module at call time). Kept for import sites and fault injection.
__all__ = [
    "TIER_LIMITS",
    "QuotaUnavailableError",
    "UserBucket",
    "UserRateLimiter",
    "async_session_scope",
    "user_ratelimit_stats",
    "user_ratelimiter",
]


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
        # Per-bucket quota freshness TTL. The sync interval used to be a
        # single process-wide timestamp, which is wrong once there is more
        # than one bucket: whichever request happened to sync first set the
        # timestamp for everyone, so other users' buckets never refreshed.
        self.quota_ttl = 60.0

    def _get_limits(self, tier: str) -> dict[str, int]:
        """Get rate limits for a tier."""
        return TIER_LIMITS.get(tier.upper(), TIER_LIMITS["FREE"])

    def _get_quota_reset_timestamp(self) -> float:
        """Get the timestamp for the next monthly quota reset (1st of next month)."""
        return user_ratelimit_quota.quota_reset_timestamp()

    async def _load_quota_from_db(self, api_key_id: str) -> int:
        """Load current month's quota usage from database (fail-closed)."""
        return await user_ratelimit_quota.load_quota_from_db(api_key_id)

    async def _sync_quota(self, api_key_id: str, bucket: UserBucket) -> None:
        """Refresh the cached quota for one bucket, fail-closed.

        Delegates to ``user_ratelimit_quota.sync_quota``; see that module for
        the full contract. This method is the request-path entry point: the
        HTTP middleware awaits it before ``check()``.
        """
        await user_ratelimit_quota.sync_quota(bucket, api_key_id, self.quota_ttl)

    def _new_bucket(self, now: float) -> UserBucket:
        """Build a bucket with a full burst and this month's quota window.

        Shared by ``get_bucket`` and ``check`` so a bucket created by the
        request-path quota refresh and one created inside ``check`` are
        identical. The two MUST agree: if the refresh built a bucket with a
        different burst or reset window than the one ``check`` would have
        built, the refresh would be enforcing a different budget.
        """
        return UserBucket(
            tokens=self._get_limits("FREE")["burst"],
            last_refill=now,
            quota_reset_at=self._get_quota_reset_timestamp(),
        )

    def get_bucket(self, api_key_id: str) -> UserBucket:
        """Return the live bucket for a key, creating it if it is new.

        Exposed so the request path can refresh the bucket's quota *before*
        calling ``check()``. ``check()`` re-reads the same object, so the
        refreshed usage and the unverified flag are the ones it enforces.
        """
        bucket = self._buckets.get(api_key_id)
        if bucket is None:
            bucket = self._new_bucket(time.time())
            self._buckets[api_key_id] = bucket
        return bucket

    async def refresh_quota(self, api_key_id: str) -> None:
        """Refresh a key's cached monthly quota, deny-safe on DB failure.

        Never raises: a quota read failure leaves the bucket unverified and
        ``check()`` denies it. Callers in the request path should await this
        before ``check()``.
        """
        await self._sync_quota(api_key_id, self.get_bucket(api_key_id))

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
            self._buckets[api_key_id] = self._new_bucket(now)
        bucket = self._buckets[api_key_id]

        # Check quota reset
        if now >= bucket.quota_reset_at:
            bucket.quota_used = 0
            bucket.quota_reset_at = self._get_quota_reset_timestamp()

        # Refill tokens
        elapsed = now - bucket.last_refill
        bucket.tokens = min(burst, bucket.tokens + elapsed * (rate / 60))
        bucket.last_refill = now

        # An unverified quota is a DB outage, not a zero-quota user. Deny
        # explicitly and retryably so quota enforcement cannot be bypassed by
        # taking the database down.
        if bucket.quota_unverified:
            bucket.blocked_requests += 1
            logger.warning(
                "quota_unverified_denied: %s",
                api_key_id,
                extra={"api_key_id": api_key_id},
            )
            return False, {
                "allowed": False,
                "reason": "quota_unavailable",
                "retry_after": 30,
                "message": "Quota state unavailable; retry shortly.",
            }

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
        return user_ratelimit_stats.build_stats(self._buckets, api_key_id)

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
        await user_ratelimit_quota.record_usage(
            api_key_id=api_key_id,
            user_id=user_id,
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


# Global instance
user_ratelimiter = UserRateLimiter()
