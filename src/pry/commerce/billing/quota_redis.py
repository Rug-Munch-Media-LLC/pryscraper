"""Pry — Redis-backed shared quota counters for :class:`BillingEnforcer`.

The mix-in owns the shared-store path only. In-process counters and their JSON
persistence stay in ``enforcer.py`` and are the fallback whenever Redis is
absent, unreachable or erroring. Key shapes, TTLs and the rollback-on-deny
semantics are unchanged from the original implementation.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import hashlib
import logging
import time
from datetime import date
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover
    from pry.commerce.billing.tiers import Tier

logger = logging.getLogger(__name__)

#: Rate-limit window length in seconds (fixed 60s window per key).
RATE_WINDOW_SECONDS: Final[int] = 60
#: Counter slot used when no API key is supplied.
ANON_KEY: Final[str] = "<anon>"
#: Redis namespace for shared counters (hashed key scope, never the raw key).
_REDIS_PREFIX: Final[str] = "pry:billing:"
#: Cooldown before re-dialling a Redis that just failed.
REDIS_RETRY_SECONDS: Final[float] = 30.0
#: Minimum seconds between best-effort persistence writes on the request path.
SAVE_INTERVAL_SECONDS: Final[float] = 5.0


def _current_month() -> str:
    """Return the current calendar month as ``YYYY-MM``."""
    return date.today().strftime("%Y-%m")


class RedisQuotaMixin:
    """Shared quota state in Redis, with fail-open to local counters.

    Hosts provide ``_redis``, ``_redis_url``, ``_redis_failed_at``,
    ``_last_save``, ``_persist_path`` and ``save()``.
    """

    def _redis_client(self) -> Any:
        """Pinged Redis client for shared counters, or None (with cooldown).

        Never raises — the in-process counters are the fallback.
        """
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        now = time.monotonic()
        if now - self._redis_failed_at < REDIS_RETRY_SECONDS:
            return None
        try:
            import redis

            client = redis.Redis.from_url(
                self._redis_url,
                socket_connect_timeout=0.25,
                socket_timeout=0.25,
                decode_responses=True,
            )
            client.ping()
        except Exception as e:  # noqa: BLE001 — degrade, never raise
            self._redis_failed_at = now
            logger.warning(
                "billing_quota_redis_unavailable_falling_back_to_memory",
                extra={"error": str(e)[:160]},
            )
            return None
        self._redis = client
        return client

    def _drop_redis(self, error: Exception) -> None:
        """Forget the client and start the cooldown."""
        self._redis = None
        self._redis_failed_at = time.monotonic()
        logger.warning(
            "billing_quota_redis_error_falling_back_to_memory",
            extra={"error": str(error)[:160]},
        )

    @staticmethod
    def _scope(api_key: str | None) -> str:
        """Opaque per-key scope — the raw credential never enters a key name."""
        material = api_key if api_key is not None else ANON_KEY
        return hashlib.sha256(material.encode()).hexdigest()[:32]

    @staticmethod
    def _month_ttl_seconds() -> int:
        """Seconds until the month rolls over, plus slack."""
        today = date.today()
        next_month = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        return int((next_month - today).total_seconds()) + 86_400

    def _redis_keys(self, api_key: str | None) -> tuple[str, str]:
        """(monthly-quota key, fixed-60s rate-window key) for one API key."""
        scope = self._scope(api_key)
        month = _current_month()
        window = int(time.time()) // RATE_WINDOW_SECONDS
        return (
            f"{_REDIS_PREFIX}q:{scope}:{month}",
            f"{_REDIS_PREFIX}r:{scope}:{window}",
        )

    def _check_redis(self, api_key: str | None, tier: Tier) -> bool | None:
        """Redis branch of ``check_request``; None means "use local counters"."""
        client = self._redis_client()
        if client is None:
            return None
        return self._redis_admit(client, api_key, tier)

    def _redis_admit(self, client: Any, api_key: str | None, tier: Tier) -> bool | None:
        """Reserve one request in Redis; None means "fall back to local".

        ``INCR``-then-compare (not read-then-write) so replicas cannot each
        read a count one below the limit; an over-limit increment is rolled
        back so a denied request consumes nothing. Boundary over-admission is
        bounded by the number of concurrent replicas, not by N whole quotas.
        """
        quota_key, rate_key = self._redis_keys(api_key)
        quota_used = 0
        try:
            if tier.request_quota_monthly is not None:
                quota_used = int(client.incr(quota_key))
                if quota_used == 1:
                    client.expire(quota_key, self._month_ttl_seconds())
                if quota_used > tier.request_quota_monthly:
                    client.decr(quota_key)
                    return False
            if tier.rate_limit_rpm is not None:
                rate_used = int(client.incr(rate_key))
                if rate_used == 1:
                    client.expire(rate_key, RATE_WINDOW_SECONDS * 2)
                if rate_used > tier.rate_limit_rpm:
                    client.decr(rate_key)
                    if quota_used:
                        client.decr(quota_key)
                    return False
        except Exception as e:  # noqa: BLE001 — fall back to in-process
            self._drop_redis(e)
            return None
        return True

    def _redis_usage(self, api_key: str | None) -> tuple[str, int, int] | None:
        """(month, month_requests, window_requests) from Redis, or None."""
        client = self._redis_client()
        if client is None:
            return None
        quota_key, rate_key = self._redis_keys(api_key)
        try:
            month_requests = int(client.get(quota_key) or 0)
            window_requests = int(client.get(rate_key) or 0)
        except Exception as e:  # noqa: BLE001 — stats degrade to local
            self._drop_redis(e)
            return None
        return _current_month(), month_requests, window_requests

    def _maybe_save(self) -> None:
        """Persist counters; throttled only when Redis holds the truth.

        With a shared store the file is a redundant snapshot, so per-request
        writes were pure last-writer-wins churn. Without Redis it is the only
        durable record — legacy per-request behaviour is preserved.
        """
        if self._persist_path is None:
            return
        if self._redis is None:
            self.save()
            return
        if time.monotonic() - self._last_save < SAVE_INTERVAL_SECONDS:
            return
        self.save()
