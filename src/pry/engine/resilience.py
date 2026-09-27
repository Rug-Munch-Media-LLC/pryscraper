"""Resilience primitives for Pry scrapers.

Provides circuit breakers and per-domain tier memory so the fallback chain
can skip unhealthy services and prefer the cheapest successful strategy for
a given domain. The three halves now live in their own modules and are
re-exported here, so every existing import keeps working:

* :mod:`pry.engine.resilience_circuit` — breaker state machine.
* :mod:`pry.engine.resilience_domain_memory` — learned per-domain tier
  ordering.
* :mod:`pry.engine.resilience_persistence` — optional JSON persistence.

``registry`` and the resilience ``time`` import stay defined in this module:
the contract is ``from pry.engine.resilience import registry`` plus
``monkeypatch.setattr(resilience, "registry", ...)``, and the global ``time``
module is shared with the breaker/domain-memory halves — patching
``resilience.time.time`` must keep faking the clock for all of them.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import time  # noqa: F401  - shared clock, tests patch resilience.time.time
from pathlib import Path
from typing import Any, ClassVar

from pry.engine.resilience_circuit import CircuitBreaker, CircuitState
from pry.engine.resilience_domain_memory import DomainTierMemory, TierRecord
from pry.engine.resilience_persistence import (
    DOMAIN_MEMORY_SAVE_INTERVAL,
    PRY_RESILIENCE_PERSIST_ENV,
    PRY_RESILIENCE_STATE_ENV,
    RESILIENCE_STATE_FILENAME,
    ResiliencePersistenceMixin,
    default_state_path,
)

logger = logging.getLogger(__name__)

DOMAIN_MEMORY_MAX_AGE_SECONDS = 3600

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "DomainTierMemory",
    "ResilienceRegistry",
    "TierRecord",
    "default_state_path",
    "registry",
]

# Env-var / filename knobs live in the persistence module; re-exported so
# `resilience.RESILIENCE_STATE_FILENAME` etc. keep resolving.
_ = (
    PRY_RESILIENCE_PERSIST_ENV,
    PRY_RESILIENCE_STATE_ENV,
    RESILIENCE_STATE_FILENAME,
)


class ResilienceRegistry(ResiliencePersistenceMixin):
    """Global registry for circuit breakers and domain tier memory.

    Persistence (optional): pass ``persist_path`` to enable JSON persistence
    of domain tier memory + breaker state, or call
    :meth:`~pry.engine.resilience_persistence.ResiliencePersistenceMixin.enable_persistence`.
    Loading happens lazily on enable; saves happen on domain-tier change
    (throttled), on explicit ``save()``, and on process exit. All I/O errors
    are logged and swallowed — persistence never breaks scraping.
    """

    # External services that should have circuit breakers.
    SERVICE_NAMES: ClassVar[list[str]] = [
        "flaresolverr",
        "ollama",
        "openrouter",
        "redis",
    ]

    def __init__(self, persist_path: Path | str | None = None) -> None:
        self.breakers: dict[str, CircuitBreaker] = {
            name: CircuitBreaker(name=name) for name in self.SERVICE_NAMES
        }
        self.domain_memory = DomainTierMemory()
        # Lazy JSON persistence. None = disabled (default). A path enables
        # load-on-start + save-on-change so learned intelligence survives
        # restarts. Off by default so tests/ephemeral runs never write state.
        self._persist_path: Path | None = None
        self._save_interval: float = DOMAIN_MEMORY_SAVE_INTERVAL
        self._last_save: float = 0.0
        self._dirty: bool = False
        self._atexit_registered: bool = False
        if persist_path is not None:
            self.enable_persistence(Path(persist_path))

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
        # Mark dirty so breaker state rides along on the next save/exit flush.
        # Disk writes are only triggered by domain-tier changes (the hot
        # intelligence) — breaker-only churn stays in memory until then.
        self._dirty = True

    def record_domain_tier_result(
        self,
        domain: str,
        tier: str,
        success: bool,
        latency: float = 0.0,
        *,
        cost_usd: float = 0.0,
        block_kind: str = "",
    ) -> None:
        """Record one tier outcome. The new fields are keyword-only with
        defaults so every existing caller keeps working unchanged."""
        self.domain_memory.record(
            domain, tier, success, latency, cost_usd=cost_usd, block_kind=block_kind
        )
        self._dirty = True
        self._maybe_save()

    def best_tier_for_domain(self, domain: str, candidates: list[str]) -> str | None:
        return self.domain_memory.best_tier(domain, candidates)

    def reorder_for_domain(self, domain: str, candidates: list[str]) -> list[str]:
        """Adaptively reorder ``candidates`` for ``domain`` (see DomainTierMemory)."""
        return self.domain_memory.reorder_for_domain(domain, candidates)

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


# Global singleton used by scrapers. Persistence is optional and enabled by
# default_state_path() only when the operator opts in via env vars — see
# default_state_path() for the knobs.
registry = ResilienceRegistry(persist_path=default_state_path())
