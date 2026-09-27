"""Circuit breaker primitive for Pry scrapers.

Extracted from ``pry.engine.resilience`` so the breaker state machine lives
in one place. ``resilience.py`` keeps re-exporting :class:`CircuitState` and
:class:`CircuitBreaker` — and the global ``registry`` singleton — so every
existing caller and test patch target is unchanged.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_RECOVERY_SECONDS = 30
DEFAULT_HALF_OPEN_MAX_TRIES = 2

__all__ = [
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_HALF_OPEN_MAX_TRIES",
    "DEFAULT_RECOVERY_SECONDS",
    "CircuitBreaker",
    "CircuitState",
]


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
