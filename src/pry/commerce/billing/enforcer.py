"""Pry — subscription enforcement (monthly quotas + per-minute rate limits).

Self-contained: no FastAPI, no Stripe, no crypto. Middleware calls ``check_request``.

Scope decisions
---------------
- Payment reconciliation (Stripe / x402 receipts) is OUT of scope (see the
  ``# TODO(billing)`` marker); this module only maps keys to tiers and limits.
- ``Tier.concurrent_limit`` is surfaced by :meth:`usage_stats` but NOT enforced;
  the middleware owns request lifecycle tracking.
- Shared quota lives in Redis (:class:`RedisQuotaMixin`) with local fallback.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pry.commerce.billing.quota_redis import (
    ANON_KEY as _ANON_KEY,
    RATE_WINDOW_SECONDS,
    RedisQuotaMixin,
    _current_month,
)
from pry.commerce.billing.tiers import DEFAULT_TIER, TIERS, Tier, get_tier

logger = logging.getLogger(__name__)

#: Env var holding the key→tier JSON map, e.g. ``{"sk_live_abc": "pro"}``.
ENV_KEYS: Final[str] = "PRY_BILLING_KEYS"
#: Env var pointing at a JSON file with the same shape.
ENV_KEYS_FILE: Final[str] = "PRY_BILLING_KEYS_FILE"
#: Max distinct API keys tracked in memory (bounded, FIFO eviction).
MAX_TRACKED_KEYS: Final[int] = 10_000
#: Persistence file format version.
_PERSIST_VERSION: Final[int] = 1


@dataclass
class _KeyCounter:
    """Per-key usage counters: monthly total + fixed 60s window."""

    month: str
    month_requests: int
    window_start: float
    window_requests: int


class BillingEnforcer(RedisQuotaMixin):
    """Quota + rate-limit enforcement with thread-safe in-memory counters.

    Args:
        keys_config: Key→tier mapping: dict, JSON file path, JSON string, or
            ``None`` to read ``PRY_BILLING_KEYS`` / ``PRY_BILLING_KEYS_FILE``.
            Absent keys map to FREE; unknown tier names log and fall back.
        persist_path: Optional JSON file for durable monthly counters; unset
            (default) keeps accounting in memory only, resetting on restart.
        redis_url: Redis URL override; defaults to ``PRY_REDIS_URL``.
        redis_client: Injected client (tests); disables URL resolution.
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
        # resolves from the argument, then PRY_REDIS_URL.
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

        Applies the monthly quota and per-minute rate limit; a ``None`` quota
        (FREE / ENTERPRISE) or ``None`` rpm skips that check. Thread-safe. When
        *tier* is omitted it is resolved via :meth:`resolve_tier`.
        """
        resolved = tier if tier is not None else self.resolve_tier(api_key)
        shared = self._check_redis(api_key, resolved)
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

        Keys with no traffic get a zeroed counter. ``request_quota_monthly`` /
        ``rate_limit_rpm`` / ``quota_remaining`` / ``rpm_remaining`` are ``None``
        when uncapped; ``quota_exceeded`` means the next request is rejected.
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

        Best-effort: errors are logged, never raised. Temp file then ``replace()``.
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

    # ── Internals ──────────────────────────────────────────────────
    def _counter_for(self, api_key: str | None, now: float) -> _KeyCounter:
        """Return the live counter for *api_key*, rotating month/window.

        Callers hold ``self._lock``. Counters are created lazily; at the key
        budget the least-recently-used key is evicted.
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

    @staticmethod
    def _parse_counter(item: Any) -> _KeyCounter | None:
        """Build a counter from one persisted slot; None when malformed."""
        if not isinstance(item, dict):
            return None
        try:
            return _KeyCounter(
                month=str(item["month"]),
                month_requests=int(item["month_requests"]),
                window_start=float(item["window_start"]),
                window_requests=int(item["window_requests"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

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
        self._merge_counters(raw if isinstance(raw, dict) else {})

    def _merge_counters(self, counters: dict[str, Any]) -> None:
        """Copy parsed counters into the bounded in-memory map."""
        with self._lock:
            for key, item in counters.items():
                counter = self._parse_counter(item)
                if counter is None or len(self._counters) >= MAX_TRACKED_KEYS:
                    continue
                self._counters[key] = counter


# TODO(billing): payment reconciliation — validate Stripe subscription
# status / x402 payment receipts before trusting the key→tier mapping.
# The enforcer above is intentionally provider-agnostic so the lead can
# wire reconciliation into the API middleware without touching this module.
