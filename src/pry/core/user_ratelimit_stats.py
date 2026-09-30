"""Pry — read-only statistics for the per-user rate limiter.

Builds the ``get_stats()`` payload from the limiter's in-memory bucket map.
Pure reads: no clock, no database, no mutation of the buckets it inspects.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pry.core.user_ratelimit import UserBucket


def build_stats(
    buckets: Mapping[str, UserBucket],
    api_key_id: str | None = None,
) -> dict[str, Any]:
    """Summarise the limiter's buckets for one key, or fleet-wide when no key.

    The per-key view reports FREE limits, because the tier a bucket was last
    charged at is not retained — the effective limit is applied at ``check()``
    time. Fleet-wide totals are summed straight off the bucket map.
    """
    if api_key_id:
        bucket = buckets.get(api_key_id)
        if not bucket:
            return {"error": "not_found"}
        from pry.core.user_ratelimit import TIER_LIMITS

        limits = TIER_LIMITS["FREE"]
        return {
            "api_key_id": api_key_id,
            "remaining": int(bucket.tokens),
            "limit": limits["rpm"],
            "quota_used": bucket.quota_used,
            "quota_limit": limits["quota_monthly"],
            "total_requests": bucket.total_requests,
            "blocked_requests": bucket.blocked_requests,
        }
    return {
        "active_keys": len(buckets),
        "total_requests": sum(b.total_requests for b in buckets.values()),
        "total_blocked": sum(b.blocked_requests for b in buckets.values()),
    }
