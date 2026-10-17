"""Pry — subscription enforcement (monthly quotas + per-minute rate limits).

Self-contained: no FastAPI, no Stripe, no crypto. The API middleware can
construct a :class:`BillingEnforcer` and call :meth:`BillingEnforcer.check_request`
once per request; tier resolution for a key comes from :meth:`BillingEnforcer.resolve_tier`.

Scope decisions
---------------
- Payment reconciliation (charging Stripe / validating x402 receipts) is
  deliberately OUT of scope here. The enforcer only maps API keys to tiers
  and enforces usage limits; wiring a payment provider is a documented TODO
  for the lead integrator (see the ``# TODO(billing): payment reconciliation``
  markers below).
- Active concurrency limiting (``Tier.concurrent_limit``) is exposed on the
  tier and surfaced in :meth:`usage_stats`, but NOT enforced here — the
  middleware owns request lifecycle tracking.
- Quota + rate counters live in Redis when ``PRY_REDIS_URL`` (or an injected
  client) is available: windowed ``INCR`` for the month plus a fixed 60s
  ``INCR`` bucket, so N replicas enforce ONE quota instead of N. Absent,
  unreachable or erroring Redis degrades to the in-process counters below.
- The in-process counters (thread-safe, ``MAX_TRACKED_KEYS`` FIFO) are the
  FALLBACK only. JSON persistence survives restarts; with Redis holding the
  truth its per-request whole-file write is throttled (it was last-writer-wins
  churn across replicas) and stays per-request without Redis.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from pry.commerce.billing.tiers import DEFAULT_TIER, TIERS, Tier, get_tier

logger = logging.getLogger(__name__)

#: Env var holding the key→tier JSON map, e.g. ``{"sk_live_abc": "pro"}``.
ENV_KEYS: Final[str] = "PRY_BILLING_KEYS"
#: Env var pointing at a JSON file with the same shape.
ENV_KEYS_FILE: Final[str] = "PRY_BILLING_KEYS_FILE"
#: Max distinct API keys tracked in memory (bounded, FIFO eviction).
MAX_TRACKED_KEYS: Final[int] = 10_000
#: Rate-limit window length in seconds (fixed 60s window per key).
RATE_WINDOW_SECONDS: Final[int] = 60
#: Persistence file format version.
_PERSIST_VERSION: Final[int] = 1
#: Counter slot used when no API key is supplied.
_ANON_KEY: Final[str] = "<anon>"
#: Redis namespace for shared counters (hashed key scope, never the raw key).
_REDIS_PREFIX: Final[str] = "pry:billing:"
#: Cooldown before re-dialling a Redis that just failed.
REDIS_RETRY_SECONDS: Final[float] = 30.0
#: Minimum seconds between best-effort persistence writes on the request path.
SAVE_INTERVAL_SECONDS: Final[float] = 5.0


def _current_month() -> str:
    """Return the current calendar month as ``YYYY-MM``."""
    return date.today().strftime("%Y-%m")


@dataclass
class _KeyCounter:
    """Per-key usage counters: monthly total + fixed 60s window."""

    month: str
    month_requests: int
    window_start: float
    window_requests: int


class BillingEnforcer:
    """Quota + rate-limit enforcement with thread-safe in-memory counters.

    Args:
        keys_config: Key→tier mapping. Accepts a dict, a path to a JSON
            file, a JSON string, or ``None`` to read ``PRY_BILLING_KEYS``
            (inline JSON) / ``PRY_BILLING_KEYS_FILE`` (JSON file path).
            Keys absent from the resolved config map to FREE. Unknown tier
            names in the config log a warning and fall back to FREE.
        persist_path: Optional JSON file for durable monthly counters.
            When set, counters are loaded at construction and written back
            atomically on every :meth:`check_request`. When unset (default),
            accounting is in-memory only and resets on restart. For
            high-throughput deployments prefer a periodic :meth:`save`
            instead of per-request writes.
    """

    def __init__(
        self,
        keys_config: dict[str, str] | str | Path | None = None,
        persist_path: str | Path | None = None,
        redis_url: str | None = None,
        redis_client: Any = None,
    ) -> None:
        self._lock = threading.RLock()
        self._counters: OrderedDict[str, _KeyCounter] = OrderedDict()
        self._tier_by_key: dict[str, str] = self._load_keys(keys_config)
        self._persist_path = Path(persist_path) if persist_path else None
        # Shared quota state; ``redis_client`` is the injection seam. The URL
        # resolves from the argument, then PRY_REDIS_URL. Absent/unreachable
        # -> in-process counters only.
        self._redis_url = (
            None
            if redis_client is not None
            else (redis_url if redis_url is not None else os.environ.get("PRY_REDIS_URL", ""))
        )
        self._redis: Any = redis_client
        self._redis_failed_at = 0.0
        self._last_save = 0.0
        if self._persist_path is not None:
            self._load_persisted()

    # ── Tier resolution ────────────────────────────────────────────
    def resolve_tier(self, api_key: str | None) -> Tier:
        """Resolve *api_key* to its tier; missing/None keys get FREE."""
        if api_key is None:
            return DEFAULT_TIER
        tier_name = self._tier_by_key.get(api_key)
        if tier_name is None:
            return DEFAULT_TIER
        return get_tier(tier_name)

    # ── Enforcement ────────────────────────────────────────────────
    def check_request(self, api_key: str | None, tier: Tier | None = None) -> bool:
        """Record one request and return True if it is allowed.

        Applies the tier's monthly quota and per-minute rate limit; tiers
        with ``None`` quota (FREE / ENTERPRISE) or ``None`` rpm skip the
        respective check. Thread-safe: callers may invoke this from many
        worker threads without lost updates.

        When *tier* is omitted it is resolved from *api_key* via
        :meth:`resolve_tier`, so middleware can also pass an already
        resolved tier to avoid a second lookup.
        """
        resolved = tier if tier is not None else self.resolve_tier(api_key)
        client = self._redis_client()
        if client is not None:
            shared = self._redis_admit(client, api_key, resolved)
            if shared is not None:
                return shared
        now = time.monotonic()
        with self._lock:
            counter = self._counter_for(api_key, now)
            if resolved.request_quota_monthly is not None and (
                counter.month_requests >= resolved.request_quota_monthly
            ):
                return False
            if resolved.rate_limit_rpm is not None and (
                counter.window_requests >= resolved.rate_limit_rpm
            ):
                return False
            counter.month_requests += 1
            counter.window_requests += 1
        self._maybe_save()
        return True

    def usage_stats(self, api_key: str | None) -> dict[str, Any]:
        """Return usage vs quota for *api_key*.

        Keys with no recorded traffic get a zeroed counter. Fields
        ``request_quota_monthly`` / ``rate_limit_rpm`` / ``quota_remaining``
        / ``rpm_remaining`` are ``None`` when the tier has no cap;
        ``quota_exceeded`` is True when the next request would be rejected
        on the monthly quota alone.
        """
        tier = self.resolve_tier(api_key)
        now = time.monotonic()
        shared = self._redis_usage(api_key)
        with self._lock:
            counter = self._counter_for(api_key, now)
            month = counter.month
            month_requests = counter.month_requests
            window_requests = counter.window_requests
        if shared is not None:
            month, month_requests, window_requests = shared
        quota = tier.request_quota_monthly
        rpm = tier.rate_limit_rpm
        return {
            "api_key": api_key,
            "tier": tier.name,
            "price_usd_monthly": tier.price_usd_monthly,
            "request_quota_monthly": quota,
            "concurrent_limit": tier.concurrent_limit,
            "rate_limit_rpm": rpm,
            "feature_flags": sorted(tier.feature_flags),
            "month": month,
            "month_requests": month_requests,
            "quota_remaining": None if quota is None else max(0, quota - month_requests),
            "quota_exceeded": quota is not None and month_requests >= quota,
            "window_requests": window_requests,
            "rpm_remaining": None if rpm is None else max(0, rpm - window_requests),
        }

    # ── Maintenance ────────────────────────────────────────────────
    def save(self) -> None:
        """Atomically persist counters to ``persist_path`` (if configured).

        Best-effort: I/O errors are logged, never raised. Writes go to a
        temp file then ``replace()`` so a crash mid-write cannot corrupt
        the previous snapshot.
        """
        if self._persist_path is None:
            return
        with self._lock:
            payload: dict[str, Any] = {
                "version": _PERSIST_VERSION,
                "counters": {
                    key: {
                        "month": counter.month,
                        "month_requests": counter.month_requests,
                        "window_start": counter.window_start,
                        "window_requests": counter.window_requests,
                    }
                    for key, counter in self._counters.items()
                },
            }
        self._last_save = time.monotonic()
        tmp_path = self._persist_path.with_name(f"{self._persist_path.name}.tmp")
        try:
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.replace(self._persist_path)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            logger.error("Failed to persist billing counters to %s: %s", self._persist_path, exc)

    def reset(self) -> None:
        """Clear all in-memory usage counters (e.g. for tests)."""
        with self._lock:
            self._counters.clear()

    # ── Shared (Redis) counters ────────────────────────────────────
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
        material = api_key if api_key is not None else _ANON_KEY
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

    # ── Internals ──────────────────────────────────────────────────
    def _counter_for(self, api_key: str | None, now: float) -> _KeyCounter:
        """Return the live counter for *api_key*, rotating month/window.

        Callers must hold ``self._lock``. New counters are created lazily;
        when the tracked-key budget is exhausted the least-recently-used
        key is evicted (FIFO via ``move_to_end``).
        """
        key = api_key if api_key is not None else _ANON_KEY
        counter = self._counters.get(key)
        if counter is None:
            if len(self._counters) >= MAX_TRACKED_KEYS:
                self._counters.popitem(last=False)
            counter = _KeyCounter(
                month=_current_month(),
                month_requests=0,
                window_start=now,
                window_requests=0,
            )
            self._counters[key] = counter
            return counter
        self._counters.move_to_end(key)
        if counter.month != _current_month():
            counter.month = _current_month()
            counter.month_requests = 0
        if now - counter.window_start >= RATE_WINDOW_SECONDS:
            counter.window_start = now
            counter.window_requests = 0
        return counter

    def _load_keys(self, keys_config: dict[str, str] | str | Path | None) -> dict[str, str]:
        """Resolve the key→tier mapping from config param, then env vars."""
        raw: dict[str, str] = {}
        if keys_config is not None:
            if isinstance(keys_config, dict):
                raw = dict(keys_config)
            elif isinstance(keys_config, Path):
                raw = self._read_json_file(keys_config)
            elif keys_config.strip().startswith("{"):
                raw = self._parse_json(keys_config, source="keys_config")
            else:
                raw = self._read_json_file(Path(keys_config))
        else:
            env_value = os.environ.get(ENV_KEYS)
            if env_value:
                raw = self._parse_json(env_value, source=ENV_KEYS)
            else:
                env_file = os.environ.get(ENV_KEYS_FILE)
                if env_file:
                    raw = self._read_json_file(Path(env_file))

        tier_by_key: dict[str, str] = {}
        for key, tier_name in raw.items():
            normalized = str(tier_name).strip().lower()
            if normalized not in TIERS:
                logger.warning(
                    "Billing config maps key to unknown tier %r; falling back to free",
                    tier_name,
                )
                normalized = "free"
            tier_by_key[key] = normalized
        return tier_by_key

    @staticmethod
    def _parse_json(text: str, source: str) -> dict[str, str]:
        """Parse a JSON object of key→tier-name; degrade to {} on error."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("Billing config %s is not valid JSON: %s", source, exc)
            return {}
        if not isinstance(data, dict):
            logger.error("Billing config %s must be a JSON object", source)
            return {}
        out: dict[str, str] = {}
        for key, value in data.items():
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                out[str(key)] = str(value)
        return out

    @classmethod
    def _read_json_file(cls, path: Path) -> dict[str, str]:
        """Read and parse a JSON config file; degrade to {} on error."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Cannot read billing config file %s: %s", path, exc)
            return {}
        return cls._parse_json(text, str(path))

    def _load_persisted(self) -> None:
        """Load counters from ``persist_path`` at construction (if any)."""
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            payload = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(
                "Ignoring unreadable billing persistence file %s: %s",
                self._persist_path,
                exc,
            )
            return
        if not isinstance(payload, dict) or payload.get("version") != _PERSIST_VERSION:
            logger.warning("Ignoring incompatible billing persistence file %s", self._persist_path)
            return
        raw = payload.get("counters")
        if not isinstance(raw, dict):
            return
        with self._lock:
            for key, item in raw.items():
                if not isinstance(item, dict) or len(self._counters) >= MAX_TRACKED_KEYS:
                    continue
                try:
                    counter = _KeyCounter(
                        month=str(item["month"]),
                        month_requests=int(item["month_requests"]),
                        window_start=float(item["window_start"]),
                        window_requests=int(item["window_requests"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                self._counters[key] = counter


# TODO(billing): payment reconciliation — validate Stripe subscription
# status / x402 payment receipts before trusting the key→tier mapping.
# The enforcer above is intentionally provider-agnostic so the lead can
# wire reconciliation into the API middleware without touching this module.
