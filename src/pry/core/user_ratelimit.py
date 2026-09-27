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
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from pry.core.db import Usage, async_session_scope

logger = logging.getLogger(__name__)

# Tier-based default limits
TIER_LIMITS = {
    "FREE": {"rpm": 60, "quota_monthly": 10_000, "burst": 100},
    "PRO": {"rpm": 300, "quota_monthly": 100_000, "burst": 500},
    "ENTERPRISE": {"rpm": 1200, "quota_monthly": 1_000_000, "burst": 2000},
    # x402 pay-per-request: every call is already paid for on-chain, so the
    # rate limit is a burst/abuse guard, not a revenue gate. Higher than FREE
    # so a paying caller is never throttled below what they paid for, but
    # still bounded so a single caller cannot hammer a target domain.
    "X402": {"rpm": 600, "quota_monthly": 1_000_000, "burst": 1000},
}


@dataclass
class UserBucket:
    """Token bucket for a specific user/API key."""

    tokens: float
    last_refill: float
    total_requests: int = 0
    blocked_requests: int = 0
    quota_used: float = 0.0
    quota_reset_at: float = 0.0
    # True when the last quota sync failed and the stored quota_used is
    # UNVERIFIED. Callers must deny: an unverified bucket is fail-closed, not
    # a user with zero usage.
    quota_unverified: bool = False
    # When the last successful quota read happened. A bucket that has NEVER
    # synced has quota_synced_at == 0.0, which is stale for every TTL and
    # so forces the first request through the sync path.
    quota_synced_at: float = 0.0


class QuotaUnavailableError(RuntimeError):
    """Raised when the monthly quota cannot be read from the database.

    Fail-closed. During a DB outage every bucket's usage is unknown, so
    treating the read as ``0`` would advertise an UNLIMITED quota to every
    user and turn a database failure into a quota/rate-limit bypass. The
    check instead denies with an explicit, retryable reason.
    """


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
        except SQLAlchemyError as e:
            # FAIL-CLOSED. Returning 0 here would read as "this user has used
            # no quota", i.e. an unlimited user, so a database outage would
            # silently disable quota enforcement fleet-wide. Deny instead.
            logger.error(
                "quota_read_failed_denying: %s",
                e,
                extra={"api_key_id": api_key_id},
            )
            raise QuotaUnavailableError(
                "quota state unavailable; denying request rather than assuming zero usage"
            ) from e

    async def _sync_quota(self, api_key_id: str, bucket: UserBucket) -> None:
        """Refresh the cached quota for one bucket, fail-closed.

        This is the request-path entry point: the HTTP middleware awaits it
        before ``check()`` so a database outage actually reaches the deny
        branch. It only touches the database when the cached quota is older
        than ``quota_ttl``; a fresh bucket is served from cache (a DB round
        trip per request would make the limiter the slowest thing in the
        request).

        On a read failure the bucket is marked unverified rather than being
        reset to zero — the previous usage total is kept and the bucket is
        denied until a later sync succeeds.
        """
        now = time.time()
        if now - bucket.quota_synced_at <= self.quota_ttl:
            return
        try:
            bucket.quota_used = await self._load_quota_from_db(api_key_id)
        except QuotaUnavailableError:
            bucket.quota_unverified = True
        else:
            bucket.quota_unverified = False
            bucket.quota_synced_at = now

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
        except (SQLAlchemyError, RuntimeError, OSError) as e:
            # Best-effort contract: usage recording must never break the
            # request. Covers DB driver errors, session-scope failures and
            # I/O errors; programming errors still surface.
            logger.warning("usage_recording_failed: %s", e)


# Global instance
user_ratelimiter = UserRateLimiter()
