"""Resilience primitives for Pry scrapers.

Provides circuit breakers and per-domain tier memory so the fallback chain
can skip unhealthy services and prefer the cheapest successful strategy for
a given domain.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_RECOVERY_SECONDS = 30
DEFAULT_HALF_OPEN_MAX_TRIES = 2
DOMAIN_MEMORY_MAX_AGE_SECONDS = 3600


class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Simple circuit breaker with exponential cooldown."""

    name: str
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    recovery_seconds: float = DEFAULT_RECOVERY_SECONDS
    half_open_max_tries: int = DEFAULT_HALF_OPEN_MAX_TRIES
    state: str = CircuitState.CLOSED
    failures: int = 0
    successes: int = 0
    last_failure_at: float = 0.0
    half_open_attempts: int = 0

    def is_allowed(self) -> bool:
        now = time.time()
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if now - self.last_failure_at >= self.recovery_seconds:
                self.state = CircuitState.HALF_OPEN
                self.half_open_attempts = 0
                logger.info("circuit_breaker_half_open", extra={"service": self.name})
                return True
            return False
        # HALF_OPEN
        return self.half_open_attempts < self.half_open_max_tries

    def record_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_attempts += 1
            if self.half_open_attempts >= self.half_open_max_tries:
                self._close()
            return
        self.successes += 1
        # Decay failures slowly on success to forgive transient blips.
        if self.failures > 0:
            self.failures -= 1

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_at = time.time()
        if self.state == CircuitState.HALF_OPEN:
            self._open()
            return
        if self.failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        if self.state != CircuitState.OPEN:
            logger.warning(
                "circuit_breaker_open",
                extra={"service": self.name, "failures": self.failures},
            )
        self.state = CircuitState.OPEN
        self.half_open_attempts = 0

    def _close(self) -> None:
        logger.info("circuit_breaker_closed", extra={"service": self.name})
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.half_open_attempts = 0


@dataclass
class TierRecord:
    successes: int = 0
    failures: int = 0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    total_latency: float = 0.0

    @property
    def score(self) -> float:
        """Higher score = more preferred. Balances success rate and recency."""
        total = self.successes + self.failures
        if total == 0:
            return 0.0
        success_rate = self.successes / total
        # Recency bonus: 1.0 if succeeded in last 5 minutes, decaying.
        recency = 0.0
        if self.last_success_at > 0:
            age = time.time() - self.last_success_at
            recency = max(0.0, 1.0 - age / DOMAIN_MEMORY_MAX_AGE_SECONDS)
        return success_rate + recency * 0.5


@dataclass
class DomainTierMemory:
    """Remember which tiers work best per domain."""

    data: dict[str, dict[str, TierRecord]] = field(default_factory=lambda: defaultdict(dict))

    def record(self, domain: str, tier: str, success: bool, latency: float = 0.0) -> None:
        rec = self.data[domain].setdefault(tier, TierRecord())
        if success:
            rec.successes += 1
            rec.last_success_at = time.time()
        else:
            rec.failures += 1
            rec.last_failure_at = time.time()
        rec.total_latency += latency

    def best_tier(self, domain: str, candidates: list[str]) -> str | None:
        records = self.data.get(domain, {})
        if not records:
            return None
        # Only consider tiers with at least one success and no recent failures.
        now = time.time()
        eligible = [
            (tier, rec)
            for tier, rec in records.items()
            if rec.successes > 0
            and (rec.last_failure_at == 0 or now - rec.last_failure_at > 300)
            and tier in candidates
        ]
        if not eligible:
            return None
        eligible.sort(key=lambda item: item[1].score, reverse=True)
        return eligible[0][0]

    def to_dict(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {
            domain: {
                tier: {
                    "successes": rec.successes,
                    "failures": rec.failures,
                    "last_success_at": rec.last_success_at,
                    "last_failure_at": rec.last_failure_at,
                    "score": round(rec.score, 3),
                }
                for tier, rec in tiers.items()
            }
            for domain, tiers in self.data.items()
        }


class ResilienceRegistry:
    """Global registry for circuit breakers and domain tier memory."""

    # External services that should have circuit breakers.
    SERVICE_NAMES: ClassVar[list[str]] = [
        "flaresolverr",
        "ollama",
        "openrouter",
        "redis",
    ]

    def __init__(self) -> None:
        self.breakers: dict[str, CircuitBreaker] = {
            name: CircuitBreaker(name=name) for name in self.SERVICE_NAMES
        }
        self.domain_memory = DomainTierMemory()

    def breaker(self, name: str) -> CircuitBreaker:
        if name not in self.breakers:
            self.breakers[name] = CircuitBreaker(name=name)
        return self.breakers[name]

    def is_service_allowed(self, name: str) -> bool:
        return self.breaker(name).is_allowed()

    def record_service_result(self, name: str, success: bool) -> None:
        breaker = self.breaker(name)
        if success:
            breaker.record_success()
        else:
            breaker.record_failure()

    def record_domain_tier_result(
        self, domain: str, tier: str, success: bool, latency: float = 0.0
    ) -> None:
        self.domain_memory.record(domain, tier, success, latency)

    def best_tier_for_domain(self, domain: str, candidates: list[str]) -> str | None:
        return self.domain_memory.best_tier(domain, candidates)

    def stats(self) -> dict[str, Any]:
        return {
            "circuit_breakers": {
                name: {
                    "state": cb.state,
                    "failures": cb.failures,
                    "successes": cb.successes,
                    "last_failure_at": cb.last_failure_at,
                }
                for name, cb in self.breakers.items()
            },
            "domain_memory": self.domain_memory.to_dict(),
        }


# Global singleton used by scrapers.
registry = ResilienceRegistry()
