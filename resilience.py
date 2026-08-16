"""Resilience primitives for Pry scrapers.

Provides circuit breakers and per-domain tier memory so the fallback chain
can skip unhealthy services and prefer the cheapest successful strategy for
a given domain.

Domain tier memory and breaker state can optionally be persisted to a small
JSON file under the configured data dir (``PRY_DATA_DIR``, default
``~/.pry``) so the learned intelligence survives restarts. Persistence is
lazy (loads on start, writes on change with a throttle, flushes on exit) and
non-fatal on I/O errors.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import atexit
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_RECOVERY_SECONDS = 30
DEFAULT_HALF_OPEN_MAX_TRIES = 2
DOMAIN_MEMORY_MAX_AGE_SECONDS = 3600

# Adaptive fallback ordering.
# A tier is skipped for a domain once it has this many samples and a success
# rate below this threshold (chronic failure) — don't waste requests on it.
DOMAIN_FAILURE_SKIP_MIN_SAMPLES = 3
DOMAIN_FAILURE_SKIP_RATE = 0.30
# A tier that just failed is demoted to the back of the chain for this long.
DOMAIN_TIER_COOLDOWN_SECONDS = 300.0

# Optional JSON persistence of domain tier memory + breaker state.
DOMAIN_MEMORY_SAVE_INTERVAL = 10.0  # throttle between lazy disk writes
RESILIENCE_STATE_FILENAME = "resilience_state.json"
PRY_RESILIENCE_PERSIST_ENV = "PRY_RESILIENCE_PERSIST"
PRY_RESILIENCE_STATE_ENV = "PRY_RESILIENCE_STATE"


def default_state_path() -> Path | None:
    """Resolve the persistence file path, or ``None`` to keep it disabled.

    Persistence is optional and off by default so tests and ephemeral runs
    never touch the real data dir. Enable with:

    - ``PRY_RESILIENCE_STATE=/path/to/state.json`` (explicit file), or
    - ``PRY_RESILIENCE_PERSIST=1`` (default file under the configured
      ``PRY_DATA_DIR``, e.g. ``~/.pry/resilience_state.json``).
    """
    explicit = os.getenv(PRY_RESILIENCE_STATE_ENV)
    if explicit:
        return Path(explicit)
    if os.getenv(PRY_RESILIENCE_PERSIST_ENV, "0") != "1":
        return None
    try:
        from paths import PRY_DATA_DIR

        return PRY_DATA_DIR / RESILIENCE_STATE_FILENAME
    except Exception:  # noqa: BLE001 - never let persistence break startup
        return Path("~/.pry").expanduser() / RESILIENCE_STATE_FILENAME


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

    def reorder_for_domain(
        self,
        domain: str,
        candidates: list[str],
        *,
        cooldown_seconds: float = DOMAIN_TIER_COOLDOWN_SECONDS,
    ) -> list[str]:
        """Return ``candidates`` reordered for ``domain`` using its history.

        The static fallback order is the baseline. On top of it:

        - Proven tiers (highest score) are promoted to the front, so the
          domain's best-known method is tried first.
        - Tiers with a recent failure (within ``cooldown_seconds``) are
          demoted to the back — a temporary cooldown, not a ban.
        - Tiers with >= ``DOMAIN_FAILURE_SKIP_MIN_SAMPLES`` samples and a
          success rate below ``DOMAIN_FAILURE_SKIP_RATE`` are skipped for
          this domain entirely (chronic failure).
        - Tiers with no history keep their static position.

        Never returns an empty list: if every candidate would be skipped the
        static order is returned so the scraper always has something to try.
        """
        records = self.data.get(domain, {})
        if not records:
            return list(candidates)

        now = time.time()
        static_index = {tier: i for i, tier in enumerate(candidates)}

        promoted: list[tuple[str, float, int]] = []  # (tier, score, static idx)
        cooldown: list[tuple[str, int]] = []  # recent failure -> back of chain
        for tier in candidates:
            rec = records.get(tier)
            if rec is None:
                promoted.append((tier, 0.0, static_index[tier]))
                continue
            total = rec.successes + rec.failures
            if total >= DOMAIN_FAILURE_SKIP_MIN_SAMPLES:
                rate = rec.successes / total
                if rate < DOMAIN_FAILURE_SKIP_RATE:
                    # Chronic failure: skip this tier for the domain.
                    continue
            if rec.last_failure_at > 0 and now - rec.last_failure_at < cooldown_seconds:
                cooldown.append((tier, static_index[tier]))
                continue
            promoted.append((tier, rec.score, static_index[tier]))

        promoted.sort(key=lambda item: (-item[1], item[2]))
        cooldown.sort(key=lambda item: item[1])
        ordered = [tier for tier, _, _ in promoted] + [tier for tier, _ in cooldown]
        return ordered or list(candidates)

    def to_dict(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {
            domain: {
                tier: {
                    "successes": rec.successes,
                    "failures": rec.failures,
                    "last_success_at": rec.last_success_at,
                    "last_failure_at": rec.last_failure_at,
                    "total_latency": rec.total_latency,
                    "score": round(rec.score, 3),
                }
                for tier, rec in tiers.items()
            }
            for domain, tiers in self.data.items()
        }


class ResilienceRegistry:
    """Global registry for circuit breakers and domain tier memory.

    Persistence (optional): pass ``persist_path`` to enable JSON persistence
    of domain tier memory + breaker state, or call :meth:`enable_persistence`.
    Loading happens lazily on enable; saves happen on domain-tier change
    (throttled), on explicit :meth:`save`, and on process exit. All I/O
    errors are logged and swallowed — persistence never breaks scraping.
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

    def enable_persistence(self, path: Path | str | None) -> None:
        """Enable lazy JSON persistence at ``path`` (``None`` disables)."""
        if path is None:
            self._persist_path = None
            self._dirty = False
            return
        self._persist_path = Path(path)
        self._load()
        if not self._atexit_registered:
            self._atexit_registered = True
            atexit.register(self.save)

    def disable_persistence(self) -> None:
        """Disable persistence and drop any pending dirty state."""
        self._persist_path = None
        self._dirty = False

    def save(self) -> bool:
        """Write current state to the persistence file. Non-fatal on errors."""
        if self._persist_path is None:
            return False
        try:
            payload = self._serialize_state()
            path = self._persist_path
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp, path)
            self._dirty = False
            self._last_save = time.time()
            return True
        except OSError as e:
            logger.debug("resilience_persist_failed", extra={"error": str(e)[:80]})
            return False

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            with open(self._persist_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            if not isinstance(payload, dict):
                return
            self._restore_state(payload)
            self._dirty = False
        except (OSError, ValueError) as e:
            logger.debug("resilience_load_failed", extra={"error": str(e)[:80]})

    def _maybe_save(self) -> None:
        """Throttled lazy save: persist at most once per interval when dirty."""
        if self._persist_path is None or not self._dirty:
            return
        now = time.time()
        if now - self._last_save >= self._save_interval:
            self.save()

    def _serialize_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "saved_at": time.time(),
            "domain_memory": self.domain_memory.to_dict(),
            "circuit_breakers": {
                name: {
                    "state": cb.state,
                    "failures": cb.failures,
                    "successes": cb.successes,
                    "last_failure_at": cb.last_failure_at,
                    "half_open_attempts": cb.half_open_attempts,
                    "failure_threshold": cb.failure_threshold,
                    "recovery_seconds": cb.recovery_seconds,
                    "half_open_max_tries": cb.half_open_max_tries,
                }
                for name, cb in self.breakers.items()
            },
        }

    def _restore_state(self, payload: dict[str, Any]) -> None:
        dm = payload.get("domain_memory")
        if isinstance(dm, dict):
            for domain, tiers in dm.items():
                if not isinstance(tiers, dict):
                    continue
                for tier, rec_data in tiers.items():
                    if not isinstance(rec_data, dict):
                        continue
                    rec = TierRecord(
                        successes=int(rec_data.get("successes", 0)),
                        failures=int(rec_data.get("failures", 0)),
                        last_success_at=float(rec_data.get("last_success_at", 0.0)),
                        last_failure_at=float(rec_data.get("last_failure_at", 0.0)),
                        total_latency=float(rec_data.get("total_latency", 0.0)),
                    )
                    self.domain_memory.data[domain][tier] = rec
        cbs = payload.get("circuit_breakers")
        if isinstance(cbs, dict):
            for name, cb_data in cbs.items():
                if not isinstance(cb_data, dict):
                    continue
                cb = self.breaker(name)
                cb.state = cb_data.get("state", CircuitState.CLOSED)
                cb.failures = int(cb_data.get("failures", 0))
                cb.successes = int(cb_data.get("successes", 0))
                cb.last_failure_at = float(cb_data.get("last_failure_at", 0.0))
                cb.half_open_attempts = int(cb_data.get("half_open_attempts", 0))
                cb.failure_threshold = int(cb_data.get("failure_threshold", cb.failure_threshold))
                cb.recovery_seconds = float(cb_data.get("recovery_seconds", cb.recovery_seconds))
                cb.half_open_max_tries = int(
                    cb_data.get("half_open_max_tries", cb.half_open_max_tries)
                )

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
        self, domain: str, tier: str, success: bool, latency: float = 0.0
    ) -> None:
        self.domain_memory.record(domain, tier, success, latency)
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
