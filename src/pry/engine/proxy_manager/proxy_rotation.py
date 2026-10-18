"""Health-aware proxy selection: rotation, affinity and quarantine.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import logging
import threading
import time

from pry.engine.proxy_manager.proxy_types import ProxyConfig

logger = logging.getLogger(__name__)

_selection_index = 0
_selection_lock = threading.Lock()


def reset_selection_rotation() -> None:
    """Reset the tie-break rotation used by :meth:`ProxyManager.get_best_proxy`."""
    global _selection_index
    with _selection_lock:
        _selection_index = 0


class ProxyRotationMixin:
    """Candidate collection, per-domain affinity and quarantine selection."""

    #: How long a per-domain affinity win/failure record stays valid.
    affinity_ttl_seconds = 3600

    def get_proxy_url(self) -> str | None:
        """Get the healthiest active proxy URL. Returns None if no usable proxy configured.

        Never returns a dead/cooldown proxy: if the only candidate is tripped,
        this returns None so callers fall back to the next tier instead of
        burning the last-resort proxy tier on a known-bad endpoint.
        """
        return self.get_best_proxy()

    def _candidate_proxies(self) -> list[str]:
        """Collect the proxy URLs that are currently selectable.

        Mirrors the historical get_proxy_url() resolution per provider, but as
        a list so health scoring can pick the best one (pool > single URL).
        """
        c = self.active_config
        if c.provider == "webshare":
            pool = self.webshare_pool()
            if pool:
                return pool
            if c.proxy_url and c.proxy_url != "rotating":
                return [c.proxy_url]
            return []
        if c.provider == "free":
            if c.proxy_url and c.proxy_url != "rotating":
                return [c.proxy_url]
            return []
        cred = self.credentials.get(c.provider)
        if not cred:
            return []
        url = self._credential_proxy_url(cred)
        return [url] if url else []

    @staticmethod
    def _credential_proxy_url(cred: ProxyConfig) -> str | None:
        """Resolve a stored credential entry to a concrete proxy URL."""
        if cred.api_key:
            return f"http://{cred.api_key}@proxy.{cred.provider}.com:8000"
        if cred.username and cred.password:
            return f"{cred.proxy_type}://{cred.username}:{cred.password}@{cred.proxy_url}"
        if cred.proxy_url:
            return cred.proxy_url
        return None

    def _affinity_state(self, domain_key: str) -> tuple[dict[str, int], dict[str, float]]:
        affinity: dict[str, int] = self._health_data.setdefault("affinity", {}).setdefault(
            domain_key, {}
        )
        stamps: dict[str, float] = self._health_data.setdefault("affinity_ts", {}).setdefault(
            domain_key, {}
        )
        return affinity, stamps

    def _fresh_affinity(self, domain_key: str) -> dict[str, int]:
        """Affinity wins that are still inside the TTL; expired ones are ignored."""
        affinity, stamps = self._affinity_state(domain_key)
        if not stamps:
            return dict(affinity)  # legacy state written before TTL stamps existed
        now = time.time()
        return {
            proxy: score
            for proxy, score in affinity.items()
            if now - float(stamps.get(proxy, 0.0)) <= self.affinity_ttl_seconds
        }

    def _domain_failures(self, domain_key: str) -> dict[str, int]:
        """Failure counts per proxy for a domain (expired counts are dropped)."""
        failures: dict[str, int] = self._health_data.setdefault("domain_failures", {}).setdefault(
            domain_key, {}
        )
        _, stamps = self._affinity_state(domain_key)
        now = time.time()
        return {
            proxy: count
            for proxy, count in failures.items()
            if now - float(stamps.get(proxy, 0.0)) <= self.affinity_ttl_seconds
        }

    def _record_affinity(self, proxy_url: str, success: bool, domain: str) -> None:
        """Update domain affinity + failure count, resetting stale entries first."""
        domain_key = self._normalize_domain(domain)
        affinity, stamps = self._affinity_state(domain_key)
        now = time.time()
        if now - float(stamps.get(proxy_url, now)) > self.affinity_ttl_seconds:
            affinity[proxy_url] = 0
            self._health_data.setdefault("domain_failures", {}).setdefault(domain_key, {}).pop(
                proxy_url, None
            )
        super()._record_affinity(proxy_url, success, domain)
        stamps[proxy_url] = now
        failures: dict[str, int] = self._health_data.setdefault("domain_failures", {}).setdefault(
            domain_key, {}
        )
        if success:
            failures.pop(proxy_url, None)
        else:
            failures[proxy_url] = failures.get(proxy_url, 0) + 1

    def _rotate_ties(self, healthy: list[str], candidates: list[str]) -> str:
        """Pick the healthiest proxy; equally-scored proxies rotate round-robin.

        The cursor walks the configured pool order, so after a proxy is
        quarantined the next call lands on the following pool member rather
        than an arbitrary remaining tie.
        """
        global _selection_index
        scores = {proxy: self._health_score_of(proxy) for proxy in healthy}
        top = max(scores.values())
        ties = [proxy for proxy in healthy if scores[proxy] == top]
        if len(ties) == 1:
            return ties[0]
        order = {proxy: index for index, proxy in enumerate(candidates)}
        with _selection_lock:
            start = _selection_index % len(candidates)
            _selection_index += 1
            return next((proxy for proxy in ties if order[proxy] >= start), ties[0])

    def _domain_healthy(self, healthy: list[str], domain_key: str) -> list[str]:
        """Drop proxies that repeatedly failed for ``domain_key`` (quarantine)."""
        failures = self._domain_failures(domain_key)
        return [
            proxy
            for proxy in healthy
            if failures.get(proxy, 0) < self.consecutive_failure_threshold
        ]

    def _affinity_winner(self, healthy: list[str], domain_key: str) -> str | None:
        """Best proxy with a fresh affinity win for this domain, if any."""
        affinity = self._fresh_affinity(domain_key)
        winners = [proxy for proxy in healthy if affinity.get(proxy, 0) > 0]
        if not winners:
            return None
        return max(
            winners,
            key=lambda proxy: (affinity.get(proxy, 0), self._health_score_of(proxy)),
        )

    def get_best_proxy(self, domain: str | None = None) -> str | None:
        """Single entry point: healthiest proxy for ``domain``, or None.

        Quarantine: proxies in circuit-breaker cooldown are skipped, and a
        proxy that repeatedly failed for this specific domain is skipped for
        that domain until its affinity window (``affinity_ttl_seconds``)
        expires — failures are not retried forever.
        """
        candidates = self._candidate_proxies()
        if not candidates:
            return None
        with self._health_lock:
            healthy = [proxy for proxy in candidates if not self._is_in_cooldown(proxy)]
            domain_key = self._normalize_domain(domain) if domain else None
            if domain_key:
                healthy = self._domain_healthy(healthy, domain_key)
                if not healthy:
                    return None
                winner = self._affinity_winner(healthy, domain_key)
                if winner:
                    return winner
            if not healthy:
                return None
            return self._rotate_ties(healthy, candidates)


__all__ = ["ProxyRotationMixin", "reset_selection_rotation"]
