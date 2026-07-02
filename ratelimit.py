"""Pry — token-bucket rate limiter per IP.
Prevents abuse while keeping the service responsive."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import time


class RateLimiter:
    """Token-bucket rate limiter with per-IP tracking.

    Default: 60 requests/minute per IP, burstable to 100.
    """

    def __init__(self, default_rpm: int = 60, burst: int = 100):
        self.default_rpm = default_rpm
        self.burst = burst
        self._buckets: dict[str, dict] = {}
        self._cleanup_interval = 300  # 5 min cleanup
        self._last_cleanup = time.time()

    def check(self, ip: str, rpm: int | None = None) -> tuple[bool, dict]:
        """Check if request is allowed. Returns (allowed, stats)."""
        now = time.time()
        rate = rpm or self.default_rpm

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

    def _cleanup(self):
        """Remove stale buckets older than 1 hour."""
        now = time.time()
        stale = [ip for ip, b in self._buckets.items() if now - b["last_refill"] > 3600]
        for ip in stale:
            del self._buckets[ip]
        self._last_cleanup = now

    def get_stats(self) -> dict:
        """Get global rate limiter statistics."""
        total_active = len(self._buckets)
        total_blocked = sum(b["blocked"] for b in self._buckets.values())
        total_requests = sum(b["total"] for b in self._buckets.values())
        return {
            "active_ips": total_active,
            "total_requests": total_requests,
            "total_blocked": total_blocked,
            "default_rpm": self.default_rpm,
            "burst": self.burst,
        }
