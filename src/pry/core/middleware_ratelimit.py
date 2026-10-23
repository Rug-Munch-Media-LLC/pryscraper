"""Pry — rate-limit buckets: pre-auth IP ceiling + post-auth quota selection.

Two stages: ``preauth_check`` is a cheap in-process token bucket per client
IP evaluated BEFORE any credential/DB lookup, so anonymous floods and
garbage-key spam cost nothing; after auth, ``resolve_rate_limit`` selects the
real bucket (x402 payer, DB key, or legacy IP) and enforces the per-key quota.

REDIS-DOWN POLICY — FAIL-OPEN (degraded) for the legacy IP limiter,
FAIL-CLOSED for per-key quotas: the pre-auth bucket never touches Redis, the
legacy limiter degrades to a half-rate per-process bucket, checks served
during the outage increment ``pry_rate_limit_fail_open_total`` (visible, not
silent), and per-key quotas deny when the bucket is unverified.

Pure decision function: touches only the request scope; dependencies resolve
through the ``pry.core.middleware`` facade at call time.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import hmac
import time
from collections import OrderedDict
from typing import Any

from pry.core.middleware_common import _get_header
from pry.core.settings import settings
from pry.core.user_ratelimit import TIER_LIMITS

try:
    from prometheus_client import Counter as _PromCounter

    FAIL_OPEN = _PromCounter(
        "pry_rate_limit_fail_open_total",
        "Rate-limit checks served fail-open because Redis was unavailable",
        ["backend"],
    )
except Exception:  # noqa: BLE001 — metric registration must never break import
    FAIL_OPEN = None

# Pre-auth token buckets (ip -> [tokens, last_monotonic]); bounded table.
_PREAUTH_BUCKETS: OrderedDict[str, list[float]] = OrderedDict()
_PREAUTH_MAX_KEYS = 10_000

# Owner responses still carry the full x-ratelimit-* contract: the send wrapper
# indexes remaining/reset unconditionally, so a partial dict is a 500.
_OWNER_HEADERS = {
    "x-ratelimit-limit": "owner",
    "x-ratelimit-remaining": "owner",
    "x-ratelimit-reset": "0",
}


def _preauth_rules(credential_present: bool) -> tuple[int, float]:
    """Anonymous: per-IP default. Credentialed: the top tier, so a paying
    caller is never pre-empted while a garbage-key flood stays bounded."""
    if credential_present:
        tier = TIER_LIMITS["ENTERPRISE"]
        return int(tier["rpm"]), float(tier["burst"])
    rpm = max(60, int(settings.rate_limit_rpm))
    return rpm, float(rpm)


def preauth_check(
    ip: str, credential_present: bool = False, now: float | None = None
) -> tuple[bool, dict[str, Any]]:
    """Cheap per-IP token bucket, evaluated BEFORE authentication.

    In-process by design: the unauthenticated path must not touch Redis or
    the DB, so a ``Bearer pry_...`` garbage flood is rejected before the key
    lookup costs anything, and unknown paths are bounded before the 404
    pass-through. Anonymous and credential-bearing requests use separate
    buckets; ``ip`` must come from the trusted resolver, never raw XFF.
    """
    rpm, capacity = _preauth_rules(credential_present)
    now = time.monotonic() if now is None else now
    key = f"{ip}|{'cred' if credential_present else 'anon'}"
    state = _PREAUTH_BUCKETS.get(key)
    if state is None:
        if len(_PREAUTH_BUCKETS) >= _PREAUTH_MAX_KEYS:
            _PREAUTH_BUCKETS.popitem(last=False)
        state = [capacity, now]
        _PREAUTH_BUCKETS[key] = state
    else:
        state[0] = min(capacity, state[0] + max(0.0, now - state[1]) * (rpm / 60.0))
        state[1] = now
    if state[0] >= 1.0:
        state[0] -= 1.0
        return True, {"remaining": int(state[0]), "limit": rpm}
    retry_after = (1.0 - state[0]) * 60.0 / rpm
    return False, {
        "remaining": 0,
        "limit": rpm,
        "retry_after": round(max(retry_after, 1.0), 1),
        "reason": "ip rate limit exceeded (pre-auth)",
    }


def _note_fail_open(limiter: Any) -> None:
    """Count a legacy IP check served from the degraded memory backend."""
    degraded = settings.redis_url and getattr(limiter, "backend", "memory") == "memory"
    if degraded and FAIL_OPEN is not None:
        FAIL_OPEN.labels(backend="memory").inc()


def _owner_key(candidate: str) -> bool:
    """Constant-time match against the operator key (bytes: never raises)."""
    return hmac.compare_digest(candidate.encode(), settings.api_key.encode())


def implicit_bucket_id(api_key: str | None, x402_verified: Any) -> str:
    """Bucket id for a request with no bound API-key record (must match check())."""
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

    auth_header = _get_header(scope, b"authorization")
    api_key = None
    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]

    # Owner keys are the fleet's internal credential: they are never billed and
    # never share a tenant quota. Keep external callers paywalled; only this
    # exact key bypasses both the per-IP and per-key limiters.
    if api_key and settings.api_key and _owner_key(api_key):
        return True, {"allowed": True, "reason": "owner"}, _OWNER_HEADERS, api_key

    ratelimiter = _facade.ratelimiter
    user_ratelimiter = _facade.user_ratelimiter

    # x402 requests carry NO Authorization header (the payment IS the
    # credential); request_authorized() bound tier="X402" into
    # scope["pry_api_key"]. Route them through the user limiter so a payer
    # gets the paid limit instead of the per-IP FREE bucket.
    x402_verified = scope.get("x402_verified")

    # The x402 middleware classifies the operator's own loopback traffic as
    # caller="owner". That is the fleet's internal credential: never meter it
    # against a tenant quota (the DB quota read is not available for it).
    if x402_verified and str(x402_verified.get("caller", "")).lower() in {"owner", "internal"}:
        return True, {"allowed": True, "reason": "owner"}, _OWNER_HEADERS, api_key

    # Refresh the per-key monthly quota BEFORE check(). check() is
    # fail-closed on an unverified bucket, but only if something marked the
    # bucket unverified: without this refresh a DB outage served every user
    # at quota_used=0 (an unlimited-quota read) and the deny branch was
    # unreachable. refresh_quota() is TTL-cached and never raises.
    if x402_verified or (api_key and api_key != settings.api_key):
        key_record = scope.get("pry_api_key") or {}
        bucket_id = key_record.get("key_id") or implicit_bucket_id(api_key, x402_verified)
        await user_ratelimiter.refresh_quota(bucket_id)

    if x402_verified:
        # Bucket per payer (wallet/agent), not per IP: one payer behind many
        # IPs shares one budget; many payers behind one IP do not share one.
        key_record = scope.get("pry_api_key") or {}
        bucket_id = key_record.get("key_id") or implicit_bucket_id(api_key, x402_verified)
        allowed, stats = user_ratelimit_check(user_ratelimiter, bucket_id, key_record, "X402", 0.0)
        effective_limit = (
            key_record.get("rate_limit_rpm")
            or TIER_LIMITS.get(key_record.get("tier", "X402"), TIER_LIMITS["X402"])["rpm"]
        )
        rate_limit_headers = _user_headers(stats, effective_limit)
    elif api_key and api_key != settings.api_key:
        # DB-issued key (pry_...) validated by request_authorized(), which
        # bound the record into scope["pry_api_key"]. Use ITS per-key
        # rate_limit_rpm + quota instead of the FREE tier default.
        key_record = scope.get("pry_api_key") or {}
        bucket_id = key_record.get("key_id") or implicit_bucket_id(api_key, None)
        allowed, stats = user_ratelimit_check(user_ratelimiter, bucket_id, key_record, "FREE", 0.0)
        effective_limit = key_record.get("rate_limit_rpm") or ratelimiter.default_rpm
        rate_limit_headers = _user_headers(stats, effective_limit)
    else:
        # Legacy global key or no key — use IP-based rate limiter
        allowed, stats = ratelimiter.check(ip)
        _note_fail_open(ratelimiter)
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
    """Build the x-ratelimit-* headers (quota-used is None when withheld)."""
    return {
        "x-ratelimit-limit": str(stats.get("limit", effective_limit)),
        "x-ratelimit-remaining": str(stats.get("remaining", 0)),
        "x-ratelimit-reset": str(int(stats.get("quota_reset_at", time.time()))),
        "x-ratelimit-quota-used": str(stats["quota_used"]) if "quota_used" in stats else None,
        "x-ratelimit-quota-limit": str(stats.get("quota_limit", 10000)),
    }
