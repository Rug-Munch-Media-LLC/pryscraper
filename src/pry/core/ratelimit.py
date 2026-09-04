"""Pry — token-bucket rate limiter per IP.

Two backends behind one interface:

- **Redis** (default when ``redis_url`` is provided and reachable): fixed
  60-second window counters shared across all replicas. Required for correct
  limiting when running more than one instance.
- **In-memory** (fallback): per-process token bucket. Used when no Redis URL
  is configured, or when Redis errors — a limiter must never take the API
  down, so backend failures degrade to per-process limiting with a logged
  warning and a 30s retry cooldown before the next reconnect attempt.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_RETRY_SECONDS = 30.0

# Atomically INCR a key and set its TTL only on first increment. This avoids
# the non-atomic INCR-then-EXPIRE race where a process dying between the two
# leaves a rate-limit key with no TTL that lives forever.
_INCR_EXPIRE_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


class RateLimiter:
    """Token-bucket (memory) / fixed-window (Redis) rate limiter per IP.

    Default: 60 requests/minute per IP, burstable to 100 (memory backend).
    """

    def __init__(
        self,
        default_rpm: int = 60,
        burst: int = 100,
        redis_url: str | None = None,
    ):
        self.default_rpm = default_rpm
        self.burst = burst
        self._buckets: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._cleanup_interval = 300  # 5 min cleanup
        self._last_cleanup = time.time()

        # Redis backend state (lazy connect + failure cooldown).
        self._redis_url = redis_url or ""
        self._redis: Any = None
        self._redis_failed_at = 0.0
        self.backend = "memory"
        # Lua script registered lazily once a Redis client exists.
        self._incr_expire: Any = None

    # ── Redis backend ────────────────────────────────────────────────────────

    def _get_redis(self) -> Any:
        """Return a pinged Redis client, or None (with cooldown after failure)."""
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        now = time.time()
        if now - self._redis_failed_at < _REDIS_RETRY_SECONDS:
            return None
        try:
            import redis as redis_py

            client = redis_py.Redis.from_url(
                self._redis_url,
                socket_connect_timeout=0.25,
                socket_timeout=0.25,
                decode_responses=True,
            )
            client.ping()
            self._redis = client
            self.backend = "redis"
            logger.info("rate_limiter_redis_connected", extra={"url": self._redis_url})
            return client
        except Exception as e:  # noqa: BLE001 — any backend error must degrade, not raise
            self._redis_failed_at = now
            logger.warning(
                "rate_limiter_redis_unavailable_falling_back_to_memory",
                extra={"error": str(e)[:160]},
            )
            return None

    def _check_redis(self, ip: str, rate: int) -> tuple[bool, dict[str, Any]] | None:
        """Fixed-window check in Redis. Returns None to signal fallback."""
        client = self._get_redis()
        if client is None:
            return None
        self.backend = "redis"
        try:
            window = int(time.time()) // 60
            key = f"pry:rl:{ip}:{window}"
            if self._incr_expire is None:
                self._incr_expire = client.register_script(_INCR_EXPIRE_LUA)
            count = int(self._incr_expire(keys=[key], args=[60]))
            allowed = count <= rate
            stats: dict[str, Any] = {
                "remaining": max(0, rate - count),
                "limit": rate,
                "total": count,
                "window_reset": int((window + 1) * 60),
            }
            if not allowed:
                stats["retry_after"] = float(max(1, 60))
            return allowed, stats
        except Exception as e:  # noqa: BLE001 — same availability rule mid-flight
            # Backend broke mid-flight: drop the connection, cool down, fall
            # back to memory so the API stays available.
            self._redis = None
            self._redis_failed_at = time.time()
            self.backend = "memory"
            logger.warning(
                "rate_limiter_redis_error_falling_back_to_memory",
                extra={"error": str(e)[:160]},
            )
            return None

    # ── Public interface ─────────────────────────────────────────────────────

    def check(self, ip: str, rpm: int | None = None) -> tuple[bool, dict[str, Any]]:
        """Check if request is allowed. Returns (allowed, stats)."""
        rate = self.default_rpm if rpm is None else rpm

        redis_result = self._check_redis(ip, rate)
        if redis_result is not None:
            return redis_result

        # Redis unavailable — apply degraded multiplier to prevent N-replica
        # burst amplification (each replica independently allows full rate).
        degraded_rate = max(1, rate // 2)
        return self._check_memory(ip, degraded_rate)

    def _check_memory(self, ip: str, rate: int) -> tuple[bool, dict[str, Any]]:
        """Original per-process token bucket."""
        now = time.time()

        # Periodic cleanup
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup()

        # Get or create bucket
        if ip not in self._buckets:
            self._buckets[ip] = {
                "tokens": self.burst,
                "last_refill": now,
                "total": 0,
                "blocked": 0,
            }
            if len(self._buckets) > 50000:
                # Evict oldest entries to prevent memory DoS
                self._buckets.popitem(last=False)

        bucket = self._buckets[ip]

        # Refill tokens
        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(self.burst, bucket["tokens"] + elapsed * (rate / 60))
        bucket["last_refill"] = now
        bucket["total"] += 1

        # Check if allowed
        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            return True, {
                "remaining": int(bucket["tokens"]),
                "limit": rate,
                "total": bucket["total"],
            }
        else:
            bucket["blocked"] += 1
            wait_time = (1 - bucket["tokens"]) * (60 / rate)
            return False, {
                "remaining": 0,
                "limit": rate,
                "retry_after": round(wait_time, 1),
                "total": bucket["total"],
                "blocked": bucket["blocked"],
            }

    def _cleanup(self) -> None:
        """Remove stale buckets older than 10 minutes."""
        now = time.time()
        stale = [ip for ip, b in self._buckets.items() if now - b["last_refill"] > 600]
        for ip in stale:
            del self._buckets[ip]
        self._last_cleanup = now

    def get_stats(self) -> dict[str, Any]:
        """Get global rate limiter statistics."""
        total_active = len(self._buckets)
        total_blocked = sum(b["blocked"] for b in self._buckets.values())
        total_requests = sum(b["total"] for b in self._buckets.values())
        return {
            "backend": self.backend,
            "active_ips": total_active,
            "total_requests": total_requests,
            "total_blocked": total_blocked,
            "default_rpm": self.default_rpm,
            "burst": self.burst,
        }
