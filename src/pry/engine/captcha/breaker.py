"""Pry — per-class circuit breaker for ladder rungs.

A rung that fails ``limit`` times inside ``window_s`` for one CAPTCHA class is
skipped for the rest of the fetch, and the skip is recorded in the attempts
trail. The breaker is per fetch (constructed by the ladder), so it can never
park a rung for a later, different page.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class TierBreaker:
    """Consecutive-failure breaker keyed by ``tier:captcha_class``."""

    def __init__(
        self,
        limit: int = 3,
        window_s: float = 180.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._events: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        now = self._clock()
        kept = [t for t in self._events.get(key, []) if now - t <= self.window_s]
        self._events[key] = kept
        return kept

    def is_open(self, key: str) -> bool:
        """True when this rung must be skipped for the rest of the fetch."""
        return len(self._recent(key)) >= self.limit

    def record(self, key: str, ok: bool) -> None:
        """Record one attempt; a success closes the circuit."""
        if ok:
            self._events.pop(key, None)
            return
        self._recent(key).append(self._clock())

    def snapshot(self) -> dict[str, int]:
        """Open-circuit keys -> failure count (diagnostics/telemetry)."""
        return {k: len(self._recent(k)) for k in list(self._events) if self.is_open(k)}
