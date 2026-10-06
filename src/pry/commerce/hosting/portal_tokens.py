"""Pry — signed portal tokens (magic-link auth for the customer portal).

The portal used to authenticate by bare email query-param — anyone who
knew a customer's address could read their instances, balance, ledger and
API-key usage. This module replaces that with stateless HMAC-signed
tokens (no new table, no new deps):

- ``issue_portal_token(email)`` → opaque token encoding
  ``email | issued_at | expiry`` + HMAC-SHA256 signature.
- ``verify_portal_token(token)`` → the customer email, or ``None`` when
  the signature, expiry or shape is wrong (fail closed).

The token rides in the receipt email as a portal URL and can be re-sent
on demand via ``POST /v1/hosting/portal/request`` (rate-limited per
email — the magic-link request flow).

Signing key: ``PRY_PORTAL_SIGNING_KEY`` env var; falls back to
``PRY_API_KEY`` with a warning (so existing deployments keep working).
TTL: ``PRY_PORTAL_TOKEN_TTL_HOURS`` env, default 168 (7 days).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TTL_HOURS = 168  # 7 days
_MAX_TOKEN_AGE_HARD_CAP_HOURS = 24 * 30  # sanity cap on the env override


def _signing_key() -> bytes:
    """Resolve the portal-token signing key (dedicated secret, then API key)."""
    dedicated = os.getenv("PRY_PORTAL_SIGNING_KEY", "")
    if dedicated:
        return dedicated.encode()
    fallback = os.getenv("PRY_API_KEY", "")
    if fallback:
        logger.warning(
            "portal_signing_key_fallback",
            extra={"detail": "PRY_PORTAL_SIGNING_KEY unset — using PRY_API_KEY"},
        )
        return fallback.encode()
    # Last resort so dev/test never crashes; production must set a real key.
    logger.error("portal_signing_key_missing", extra={"detail": "no signing secret configured"})
    return b"pry-portal-dev-insecure-key"


def _ttl_seconds() -> int:
    """Portal token TTL in seconds (env-configurable, hard-capped)."""
    try:
        hours = int(os.getenv("PRY_PORTAL_TOKEN_TTL_HOURS", str(_DEFAULT_TTL_HOURS)))
    except ValueError:
        logger.warning("portal_tokens_suppressed", exc_info=True)
        hours = _DEFAULT_TTL_HOURS
    return max(1, min(hours, _MAX_TOKEN_AGE_HARD_CAP_HOURS)) * 3600


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_portal_token(email: str, *, ttl_seconds: int | None = None) -> str:
    """Create a signed portal token for *email*.

    Format: ``base64url(email|issued_at|expiry) . base64url(hmac_sha256)``
    — stateless, no server-side storage.
    """
    email = email.strip().lower()
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else _ttl_seconds()
    payload = f"{email}|{now}|{now + ttl}".encode()
    sig = hmac.new(_signing_key(), payload, hashlib.sha256).digest()
    return f"{_b64url(payload)}.{_b64url(sig)}"


def verify_portal_token(token: str) -> str | None:
    """Verify a portal token; return the customer email or ``None``.

    Fails closed on: malformed shape, bad signature, expired token.
    """
    if not token or token.count(".") != 1:
        return None
    payload_b64, sig_b64 = token.split(".", 1)
    try:
        payload = _b64url_decode(payload_b64)
        sig = _b64url_decode(sig_b64)
    except (ValueError, TypeError):
        logger.warning("portal_tokens_suppressed", exc_info=True)
        return None
    expected = hmac.new(_signing_key(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        email, issued_at, expiry = payload.decode().split("|")
        if int(expiry) < int(time.time()):
            return None
        if int(issued_at) > int(time.time()) + 60:  # clock-skew tolerance
            return None
    except (ValueError, UnicodeDecodeError):
        logger.warning("portal_tokens_suppressed", exc_info=True)
        return None
    return email.strip().lower() or None


def portal_url(email: str) -> str:
    """The portal URL with a fresh signed token (for receipt / magic-link mail)."""
    base = os.getenv("PRY_PUBLIC_BASE_URL", "https://api.pryscraper.com").rstrip("/")
    return f"{base}/v1/hosting/portal?token={issue_portal_token(email)}"


# ── Magic-link rate limiting (5 per email per hour) ────────────────────────

_PORTAL_LINK_LIMIT = 5
_PORTAL_LINK_WINDOW_SECONDS = 3600
_rate_bucket: dict[str, list[float]] = {}


def _redis_client() -> Any | None:
    """Best-effort Redis client for distributed rate limiting (None → memory)."""
    url = os.getenv("PRY_REDIS_URL", "")
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(url, socket_timeout=2, decode_responses=True)
    except Exception:  # fall back to in-memory
        logger.warning("portal_tokens_suppressed", exc_info=True)
        return None


def check_portal_link_rate(email: str) -> bool:
    """True when *email* is still under the portal-link request limit.

    Redis-backed when ``PRY_REDIS_URL`` is set, in-memory sliding window
    otherwise (single-process deployments / tests).
    """
    email = email.strip().lower()
    client = _redis_client()
    if client is not None:
        try:
            key = f"pry:portal-link:{hashlib.sha256(email.encode()).hexdigest()[:16]}"
            count = client.incr(key)
            if count == 1:
                client.expire(key, _PORTAL_LINK_WINDOW_SECONDS)
            return int(count) <= _PORTAL_LINK_LIMIT
        except Exception:  # noqa: BLE001 — Redis down → in-memory fallback
            logger.warning("portal_rate_redis_unavailable")
    now = time.monotonic()
    hits = [t for t in _rate_bucket.get(email, []) if now - t < _PORTAL_LINK_WINDOW_SECONDS]
    if len(hits) >= _PORTAL_LINK_LIMIT:
        _rate_bucket[email] = hits
        return False
    hits.append(now)
    _rate_bucket[email] = hits
    return True


def reset_portal_rate_state() -> None:
    """Clear the in-memory rate bucket (tests)."""
    _rate_bucket.clear()


__all__ = [
    "check_portal_link_rate",
    "issue_portal_token",
    "portal_url",
    "reset_portal_rate_state",
    "verify_portal_token",
]
