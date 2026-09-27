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

import atexit
import logging
import time  # noqa: F401  - shared clock, tests patch resilience.time.time
from pathlib import Path
from typing import Any, ClassVar

from pry.engine.method_stats_store import MethodStatsStore
from pry.engine.resilience_circuit import CircuitBreaker, CircuitState
from pry.engine.resilience_domain_memory import (
    DOMAIN_MEMORY_MAX_AGE_SECONDS,
    DomainTierMemory,
    TierRecord,
)
from pry.engine.resilience_persistence import (
    DOMAIN_MEMORY_SAVE_INTERVAL,
    PRY_RESILIENCE_PERSIST_ENV,
    PRY_RESILIENCE_STATE_ENV,
    RESILIENCE_STATE_FILENAME,
    ResiliencePersistenceMixin,
    default_state_path,
)
from pry.engine.tier_memory_db import warm_domain_from_db

logger = logging.getLogger(__name__)

__all__ = [
    "DOMAIN_MEMORY_MAX_AGE_SECONDS",
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

    Durability for the domain tier memory additionally goes to Postgres
    (``domain_method_stats``) through :class:`MethodStatsStore`, batched on a
    background thread. Pass ``method_stats=False`` to run purely in process
    (what tests and ephemeral runs want).
    """

    # External services that should have circuit breakers.
    SERVICE_NAMES: ClassVar[list[str]] = [
        "flaresolverr",
        "ollama",
        "openrouter",
        "redis",
    ]

    def __init__(
        self,
        persist_path: Path | str | None = None,
        *,
        method_stats: bool = True,
    ) -> None:
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
        # Durable Postgres mirror of the domain tier memory. Enabled by
        # default; the import is guarded so a checkout without SQLAlchemy (or a
        # broken environment) still scrapes, just without durability.
        self.method_stats: MethodStatsStore | None = None
        if method_stats:
            self.method_stats = _build_method_stats_store()
        if self.method_stats is not None:
            self.domain_memory.store = self.method_stats
            atexit.register(self.shutdown)

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
            "method_stats": self.method_stats.stats() if self.method_stats else None,
        }

    def warm_from_db(self, domain: str) -> int:
        """Seed the hot cache for ``domain`` from the durable store.

        Returns the number of stored rows applied; 0 when the store is absent
        or the database is unavailable. Never raises — a cold or dead database
        leaves the in-process ranking exactly as it was.
        """
        if self.method_stats is None:
            return 0
        return warm_domain_from_db(self.domain_memory, self.method_stats, domain)

    def shutdown(self) -> None:
        """Drain the durable store's buffer. Registered with atexit."""
        if self.method_stats is not None:
            self.method_stats.stop(drain=True)


def _build_method_stats_store() -> MethodStatsStore | None:
    """Best-effort construction of the durable store.

    Never raises: a store that cannot be built is ``None``, which disables
    durability and leaves the in-process memory authoritative.
    """
    try:
        return MethodStatsStore()
    except Exception as e:  # noqa: BLE001 - durability is optional by design
        logger.warning("method_stats_store_unavailable", extra={"error": f"{type(e).__name__}"})
        return None


# Global singleton used by scrapers. Persistence is optional and enabled by
# default_state_path() only when the operator opts in via env vars — see
# default_state_path() for the knobs.
registry = ResilienceRegistry(persist_path=default_state_path())
