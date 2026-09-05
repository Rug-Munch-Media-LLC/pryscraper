"""Pry — x402 facilitator health tracking + self-hosted orchestration.

Extracted from ``facilitator.py`` as mixins consumed by
:class:`~pry.payments.x402.facilitator.FacilitatorRouter`:

- ``FacilitatorHealthMixin`` — failure/success counters, latency-aware
  health scoring, weighted-random facilitator selection.
- ``SelfHostedMixin`` — self-hosted verify/settle orchestration (custom
  per-network impls + built-in SelfFacilitator), readiness/settlement
  stats probes, and payment-dict construction.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import random
import time

from pry.payments.x402.facilitator_config import FacilitatorConfig  # noqa: TC001 — runtime type
from pry.payments.x402.metrics import set_facilitator_health

logger = logging.getLogger(__name__)


class FacilitatorHealthMixin:
    """Failure/success counters, latency-aware scoring, weighted selection."""

    def _health_key(self, facilitator: FacilitatorConfig) -> str:
        return facilitator.name

    def _is_healthy(self, facilitator: FacilitatorConfig) -> bool:
        entry = self._failures.get(self._health_key(facilitator))
        if entry is None:
            return True
        count, last_failure = entry
        if time.time() - last_failure > 60:
            return True  # half-open: allow a recovery attempt
        return count < 3

    def _mark_failure(self, facilitator: FacilitatorConfig) -> None:
        key = self._health_key(facilitator)
        count, _ = self._failures.get(key, (0, 0.0))
        self._failures[key] = (count + 1, time.time())
        set_facilitator_health(key, self._is_healthy(facilitator))
        logger.warning("x402_facilitator_failure", extra={"facilitator": facilitator.name})

    def _mark_success(
        self, facilitator: FacilitatorConfig, start_time: float | None = None
    ) -> None:
        key = self._health_key(facilitator)
        self._successes[key] = self._successes.get(key, 0) + 1
        entry = self._failures.get(key)
        if entry is not None:
            count, last_failure = entry
            decayed = max(0, count - 1)
            if decayed == 0:
                self._failures.pop(key, None)
            else:
                self._failures[key] = (decayed, last_failure)
        if start_time is not None:
            latencies = self._latencies.setdefault(key, [])
            latencies.append(time.time() - start_time)
            if len(latencies) > 100:
                del latencies[:-100]
        set_facilitator_health(key, True)

    def _health_score(self, name: str) -> float:
        """Latency-aware health score: successes minus penalized failures and
        average observed latency. Higher is better; used to prefer faster,
        more reliable facilitators."""
        successes = self._successes.get(name, 0)
        failures = self._failures.get(name, (0, 0))[0]
        lats = self._latencies.get(name, [])
        avg_lat = sum(lats) / max(1, len(lats)) if lats else 0.0
        return successes - failures * 2 - avg_lat

    def _select_facilitator(self, candidates: list[FacilitatorConfig]) -> FacilitatorConfig:
        """Weighted random selection: higher health score = higher probability.

        Spreads load across healthy facilitators instead of always hitting the
        first one (prevents thundering herd on the highest-priority endpoint).
        """
        scores = [max(1, self._health_score(c.name)) for c in candidates]
        total = sum(scores)
        weights = [s / total for s in scores]
        return random.SystemRandom().choices(candidates, weights=weights, k=1)[0]

    # ── Self-hosted / custom facilitator extension points ─────────────────────
