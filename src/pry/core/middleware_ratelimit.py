"""Pry — rate-limit bucket selection for the HTTP middleware.

Picks which limiter a request is charged against (x402 payment-verified, a
DB-issued API key, or the legacy per-IP limiter), performs the pre-check
quota refresh, and builds the ``x-ratelimit-*`` response headers.

Split out of ``middleware_http`` because it is a pure decision function: it
touches no middleware instance state, only the request scope. Both
dependencies are resolved through the ``pry.core.middleware`` facade at call
time so tests that patch the facade keep working.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import time
from typing import Any

from pry.core.middleware_common import _get_header
from pry.core.settings import settings
from pry.core.user_ratelimit import TIER_LIMITS


def implicit_bucket_id(api_key: str | None, x402_verified: Any) -> str:
    """Bucket id used when the request carries no bound API-key record.

    Mirrors the ids the ``check()`` branches use so the pre-check quota
    refresh and the enforced check always agree on which bucket they mean.
    """
    if x402_verified:
        return f"x402:{x402_verified.get('caller', 'unknown')}"
    return (api_key or "")[:12]


async def resolve_rate_limit(
    scope: dict[str, Any], ip: str
) -> tuple[bool, dict[str, Any], dict[str, str], str | None]:
    """Pick the right limiter (x402 / DB key / legacy IP) and check it.

    Returns ``(allowed, stats, rate_limit_headers, api_key)``.
    """
    from pry.core import middleware as _facade

    # Rate limiting: use user rate limiter if API key present, else IP-based
    auth_header = _get_header(scope, b"authorization")
    api_key = None
    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]

    ratelimiter = _facade.ratelimiter
    user_ratelimiter = _facade.user_ratelimiter

    # x402 payment-verified requests carry NO Authorization header (the
    # on-chain payment IS the credential). request_authorized() bound an
    # identity with tier="X402" into scope["pry_api_key"]. Route them
    # through the user rate limiter with the X402 tier so a paying caller
    # gets the higher paid limit instead of being collapsed into the
    # per-IP FREE bucket (which would throttle paid traffic behind a
    # shared NAT/proxy and undercut what they paid for).
    x402_verified = scope.get("x402_verified")

    # Refresh the per-key monthly quota BEFORE check() runs. check() is
    # fail-closed on an unverified bucket, but it can only deny a bucket
    # something has marked unverified — without this refresh the
    # database read never happened on the request path, so a DB outage
    # served every user at quota_used=0 (an unlimited-quota read) and
    # the deny branch was unreachable. refresh_quota() only touches the
    # DB when the cached quota is older than its TTL, and never raises:
    # a failed read leaves the bucket unverified and check() denies.
    if x402_verified or (api_key and api_key != settings.api_key):
        key_record = scope.get("pry_api_key") or {}
        bucket_id = key_record.get("key_id") or implicit_bucket_id(api_key, x402_verified)
        await user_ratelimiter.refresh_quota(bucket_id)

    if x402_verified:
        key_record = scope.get("pry_api_key") or {}
        # Bucket per caller (the paying wallet/agent), not per IP — a
        # single payer behind many IPs must share one budget, and many
        # payers behind one IP must not share a budget.
        bucket_id = key_record.get("key_id") or implicit_bucket_id(api_key, x402_verified)
        allowed, stats = user_ratelimit_check(user_ratelimiter, bucket_id, key_record, "X402", 0.0)
        effective_limit = (
            key_record.get("rate_limit_rpm")
            or TIER_LIMITS.get(key_record.get("tier", "X402"), TIER_LIMITS["X402"])["rpm"]
        )
        rate_limit_headers = _user_headers(stats, effective_limit)
    elif api_key and api_key != settings.api_key:
        # DB-issued key (pry_...) already validated in request_authorized(),
        # which bound the authenticated record into scope["pry_api_key"].
        # Use ITS per-key rate_limit_rpm + quota (set at issue time) so
        # PRY_RATE_LIMIT_RPM / api_keys_service per-key quotas apply, instead
        # of the previous hardcoded "FREE" tier default.
        key_record = scope.get("pry_api_key") or {}
        bucket_id = key_record.get("key_id") or implicit_bucket_id(api_key, None)
        allowed, stats = user_ratelimit_check(user_ratelimiter, bucket_id, key_record, "FREE", 0.0)
        effective_limit = key_record.get("rate_limit_rpm") or ratelimiter.default_rpm
        rate_limit_headers = _user_headers(stats, effective_limit)
    else:
        # Legacy global key or no key — use IP-based rate limiter
        allowed, stats = ratelimiter.check(ip)
        rate_limit_headers = {
            "x-ratelimit-limit": str(ratelimiter.default_rpm),
            "x-ratelimit-remaining": str(stats.get("remaining", 0)),
            "x-ratelimit-reset": str(stats.get("retry_after", 1)),
        }
    return allowed, stats, rate_limit_headers, api_key


def user_ratelimit_check(
    user_ratelimiter: Any,
    bucket_id: str,
    key_record: dict[str, Any],
    default_tier: str,
    cost_usd: float,
) -> tuple[bool, dict[str, Any]]:
    """Charge one user-scoped check, applying the key record's own limits."""
    return user_ratelimiter.check(
        api_key_id=bucket_id,
        tier=key_record.get("tier", default_tier),
        rpm=key_record.get("rate_limit_rpm"),
        quota_monthly=key_record.get("quota_monthly"),
        cost_usd=cost_usd,
    )


def _user_headers(stats: dict[str, Any], effective_limit: Any) -> dict[str, Any]:
    """Build the x-ratelimit-* header map for a user-scoped check.

    ``x-ratelimit-quota-used`` is ``None`` when the limiter withheld it, so
    the rejection path can omit the header rather than emit a fabricated 0.
    """
    return {
        "x-ratelimit-limit": str(stats.get("limit", effective_limit)),
        "x-ratelimit-remaining": str(stats.get("remaining", 0)),
        "x-ratelimit-reset": str(int(stats.get("quota_reset_at", time.time()))),
        "x-ratelimit-quota-used": str(stats["quota_used"]) if "quota_used" in stats else None,
        "x-ratelimit-quota-limit": str(stats.get("quota_limit", 10000)),
    }
