"""Pry — data model for the per-user rate limiter.

The token bucket, the tier limit table and the fail-closed quota exception.
Kept apart from the limiter's behaviour so the shape can be imported without
pulling in the request-path logic.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from dataclasses import dataclass

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
