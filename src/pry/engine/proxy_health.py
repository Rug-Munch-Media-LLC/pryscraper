"""Pry — Proxy health intelligence (rolling-window scoring + circuit breaker).

Split out of :mod:`pry.engine.proxy_manager`. :class:`ProxyHealthMixin` is
mixed into :class:`pry.engine.proxy_manager.ProxyManager`, which owns the
health state (``_health_data`` / ``_health_lock``) and the tunable class
attributes (``health_window_size``, ``consecutive_failure_threshold``,
``cooldown_seconds``) so tests can shrink them per-instance.

Proxies are the LAST-RESORT fallback tier, so only healthy, known-good
proxies should ever be returned by ``get_proxy_url()``/``get_best_proxy()``.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import threading
    from pathlib import Path

logger = logging.getLogger(__name__)

#: Max result samples kept per proxy in the rolling window.
HEALTH_WINDOW_SIZE = 100
#: Consecutive failures that trip the circuit breaker (marks proxy dead).
CONSECUTIVE_FAILURE_THRESHOLD = 3
#: Seconds a tripped proxy stays in cooldown before it may be retried.
COOLDOWN_SECONDS = 300

#: Error signatures that mean the SITE blocked us -> premium proxy helps.
BLOCK_SIGNATURES: tuple[str, ...] = (
    "cloudflare",
    "cf-",
    "challenge",
    "captcha",
    "turnstile",
    "datadome",
    "akamai",
    "403",
    "429",
    "rate limit",
    "rate_limit",
    "blocked",
    "blocking",
    "access denied",
    "unusual traffic",
    "attention required",
    "just a moment",
    "forbidden",
    "timeout",
    "timed out",
    "timed_out",
)

#: Generic connectivity failures a premium proxy will NOT fix. When an error
#: is purely one of these (no block signature), do not recommend premium.
NETWORK_ERROR_SIGNATURES: tuple[str, ...] = (
    "connection refused",
    "connection reset",
    "connectionerror",
    "econnrefused",
    "econnreset",
    "dns",
    "gaierror",
    "no route to host",
    "network unreachable",
    "unreachable host",
    "socket closed",
    "socket error",
    "proxy error",
    "tunnel",
    "ssl handshake",
    "nodename nor servname",
)


class ProxyHealthMixin:
    """Rolling-window health scoring + circuit breaker for proxy selection.

    Expects the host class to provide: ``health_file`` (Path),
    ``_health_data`` (dict), ``_health_lock`` (threading.Lock), and the
    tunable attrs ``health_window_size`` / ``consecutive_failure_threshold``
    / ``cooldown_seconds``.
    """

    # Host-supplied state (declared here for type-checking only; the concrete
    # ``ProxyManager.__init__`` assigns them). Bare annotations create no
    # runtime attributes, so mixin behaviour is unchanged.
    health_file: Path
    _health_data: dict[str, Any]
    _health_lock: threading.Lock
    health_window_size: int
    consecutive_failure_threshold: int
    cooldown_seconds: int

    def _candidate_proxies(self) -> list[str]:
        """Return configured proxy URLs (host-supplied; see ProxyManager)."""
        raise NotImplementedError

    # ── Health state persistence ────────────────────────────────
    def _load_health(self) -> dict[str, Any]:
        """Load persisted proxy health state (rolling samples + affinity)."""
        if self.health_file.exists():
            try:
                data = json.loads(self.health_file.read_text())
                if isinstance(data, dict):
                    data.setdefault("version", 1)
                    data.setdefault("proxies", {})
                    data.setdefault("affinity", {})
                    return data
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("proxy_state_load_failed", extra={"error": str(e)[:160]})
        return {"version": 1, "proxies": {}, "affinity": {}}

    def _save_health(self) -> None:
        try:
            self.health_file.write_text(json.dumps(self._health_data, indent=2, default=str))
        except OSError as e:
            logger.debug("proxy_health_save_failed", extra={"error": str(e)[:80]})

    # ── Health bookkeeping ──────────────────────────────────────
    def _ensure_proxy_entry(self, proxy_url: str) -> dict[str, Any]:
        """Get (creating if needed) the health entry for a proxy URL."""
        proxies: dict[str, Any] = self._health_data.setdefault("proxies", {})
        entry: dict[str, Any] = proxies.setdefault(
            proxy_url, {"samples": [], "consecutive_failures": 0, "cooldown_until": 0.0}
        )
        entry.setdefault("samples", [])
        entry.setdefault("consecutive_failures", 0)
        entry.setdefault("cooldown_until", 0.0)
        return entry

    def _is_in_cooldown(self, proxy_url: str) -> bool:
        """Whether a proxy is currently tripped by the circuit breaker."""
        entry: dict[str, Any] | None = self._health_data["proxies"].get(proxy_url)
        if not entry:
            return False
        return bool(entry.get("cooldown_until", 0.0) > time.time())

    def _health_score_of(self, proxy_url: str) -> float:
        """Score a proxy in [0, 1]: 0.7 * success-rate + 0.3 * latency score.

        Unknown proxies (no samples yet) get a neutral 0.5 so they are
        preferred over known-bad ones but not over proven-good ones.
        """
        entry = self._health_data["proxies"].get(proxy_url)
        if not entry or not entry.get("samples"):
            return 0.5
        samples = entry["samples"]
        successes = sum(1 for _, ok, _ in samples if ok)
        success_rate = successes / len(samples)
        latencies = [lat for _, _, lat in samples if lat is not None]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        # 10s+ latency scores 0; sub-second scores ~0.9+.
        latency_score = max(0.0, 1.0 - avg_latency / 10.0)
        return round(0.7 * success_rate + 0.3 * latency_score, 4)

    def record_proxy_result(
        self, proxy_url: str, success: bool, latency: float, domain: str | None = None
    ) -> None:
        """Record a proxy outcome for health scoring (rolling window).

        On success, resets the consecutive-failure counter and bumps
        per-domain affinity. On failure, increments the counter and trips
        the circuit breaker (cooldown) once the threshold is reached.
        State is persisted to the data-dir JSON file.
        """
        with self._health_lock:
            entry = self._ensure_proxy_entry(proxy_url)
            samples = entry["samples"]
            samples.append([time.time(), bool(success), max(0.0, float(latency))])
            if len(samples) > self.health_window_size:
                del samples[: len(samples) - self.health_window_size]
            entry["consecutive_failures"] = entry["consecutive_failures"] + 1 if not success else 0
            if not success and entry["consecutive_failures"] >= self.consecutive_failure_threshold:
                entry["cooldown_until"] = time.time() + self.cooldown_seconds
            if domain:
                self._record_affinity(proxy_url, success, domain)
            self._save_health()

    def _record_affinity(self, proxy_url: str, success: bool, domain: str) -> None:
        """Update per-domain affinity: which proxy worked for this domain."""
        domain_key = self._normalize_domain(domain)
        aff = self._health_data.setdefault("affinity", {}).setdefault(domain_key, {})
        if success:
            aff[proxy_url] = aff.get(proxy_url, 0) + 1
        else:
            current = aff.get(proxy_url, 0)
            if current > 0:
                aff[proxy_url] = current - 1

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        """Normalize a URL/host to a bare lowercase domain for affinity keys."""
        d = domain.strip().lower()
        if "://" in d:
            d = d.split("://", 1)[1]
        d = d.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
        if d.startswith("www."):
            d = d[4:]
        return d

    # ── Health-aware selection ──────────────────────────────────
    def get_best_proxy(self, domain: str | None = None) -> str | None:
        """Return the healthiest available proxy, honoring per-domain affinity.

        - Skips proxies in cooldown (circuit breaker).
        - When a domain is given and a proxy previously succeeded for it, that
          proxy is preferred (still only if healthy).
        - Otherwise returns the highest health-scored proxy; ties break toward
          the first configured candidate.
        """
        candidates = self._candidate_proxies()
        if not candidates:
            return None
        with self._health_lock:
            healthy = [p for p in candidates if not self._is_in_cooldown(p)]
            if not healthy:
                return None
            domain_key = self._normalize_domain(domain) if domain else None
            if domain_key:
                affinity = self._health_data.get("affinity", {}).get(domain_key, {})
                winners = [p for p in healthy if affinity.get(p, 0) > 0]
                if winners:
                    best: str = max(
                        winners, key=lambda p: (affinity.get(p, 0), self._health_score_of(p))
                    )
                    return best
            return max(healthy, key=self._health_score_of)

    def proxy_health_summary(self, proxy_url: str) -> dict[str, Any]:
        """Return a health summary for a proxy (observability / tests)."""
        with self._health_lock:
            entry = self._health_data["proxies"].get(proxy_url)
            if not entry or not entry.get("samples"):
                return {"proxy_url": proxy_url, "known": False}
            samples = entry["samples"]
            successes = sum(1 for _, ok, _ in samples if ok)
            latencies = [lat for _, _, lat in samples]
            return {
                "proxy_url": proxy_url,
                "known": True,
                "success_rate": round(successes / len(samples), 3),
                "avg_latency": round(sum(latencies) / len(latencies), 3),
                "samples": len(samples),
                "consecutive_failures": entry.get("consecutive_failures", 0),
                "in_cooldown": self._is_in_cooldown(proxy_url),
                "cooldown_until": entry.get("cooldown_until", 0.0),
                "score": self._health_score_of(proxy_url),
            }

    def test_proxy(
        self, proxy_url: str, test_url: str = "https://httpbin.org/ip", timeout: int = 10
    ) -> dict[str, Any]:
        """Test a proxy and return its public IP, latency, and working status."""
        import httpx

        start = time.time()
        try:
            with httpx.Client(proxy=proxy_url, timeout=timeout) as c:
                r = c.get(test_url)
                elapsed = time.time() - start
                return {
                    "working": r.is_success,
                    "latency": round(elapsed, 2),
                    "ip": r.text[:100] if r.is_success else "",
                    "status": r.status_code,
                }
        except (httpx.HTTPError, httpx.RequestError) as e:
            return {"working": False, "error": str(e)[:100]}

    def needs_premium_proxy(self, last_error: str) -> bool:
        """Determine if we need a premium proxy based on the error type.

        Only block/rate-limit signatures (Cloudflare, 403, captcha, timeout)
        recommend a premium proxy. Generic connectivity failures (connection
        refused, DNS errors, resets) do NOT — a premium proxy cannot fix a
        broken network path, so we keep the free fallback tier instead.
        """
        if not last_error:
            return False
        err = last_error.lower()
        has_block = any(sig in err for sig in BLOCK_SIGNATURES)
        if has_block and any(sig in err for sig in NETWORK_ERROR_SIGNATURES):
            # Ambiguous error: an explicit block signature (e.g. Cloudflare)
            # wins over a generic connectivity signal present in the message.
            return True
        if any(sig in err for sig in NETWORK_ERROR_SIGNATURES):
            return False
        return has_block
