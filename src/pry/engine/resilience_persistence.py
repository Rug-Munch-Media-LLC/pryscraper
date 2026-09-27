"""Optional JSON persistence for the resilience registry.

Extracted from ``pry.engine.resilience`` as a mixin so the load/save/serialize
plumbing — and the throttle + dirty-flag policy — lives apart from the
registry's scrape-time surface. ``ResilienceRegistry`` inherits
:class:`ResiliencePersistenceMixin`, so ``reg.save()``,
``reg.enable_persistence()`` and ``reg._restore_state(...)`` (used directly by
``tests/test_tier_score.py``) are unchanged on the registry instance.
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
from pathlib import Path
from typing import Any

from pry.engine.resilience_circuit import CircuitState
from pry.engine.resilience_domain_memory import TierRecord

logger = logging.getLogger(__name__)

# Optional JSON persistence of domain tier memory + breaker state.
DOMAIN_MEMORY_SAVE_INTERVAL = 10.0  # throttle between lazy disk writes
RESILIENCE_STATE_FILENAME = "resilience_state.json"
PRY_RESILIENCE_PERSIST_ENV = "PRY_RESILIENCE_PERSIST"
PRY_RESILIENCE_STATE_ENV = "PRY_RESILIENCE_STATE"

__all__ = [
    "DOMAIN_MEMORY_SAVE_INTERVAL",
    "PRY_RESILIENCE_PERSIST_ENV",
    "PRY_RESILIENCE_STATE_ENV",
    "RESILIENCE_STATE_FILENAME",
    "ResiliencePersistenceMixin",
    "default_state_path",
]


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
        from pry.core.paths import PRY_DATA_DIR

        return PRY_DATA_DIR / RESILIENCE_STATE_FILENAME
    except Exception:  # noqa: BLE001 - never let persistence break startup
        return Path("~/.pry").expanduser() / RESILIENCE_STATE_FILENAME


class ResiliencePersistenceMixin:
    """Lazy, throttled, non-fatal JSON persistence for a resilience registry.

    Expects the host object to provide ``breakers`` (dict of
    :class:`~pry.engine.resilience_circuit.CircuitBreaker`) and
    ``domain_memory`` (a
    :class:`~pry.engine.resilience_domain_memory.DomainTierMemory`), plus the
    ``_persist_path`` / ``_save_interval`` / ``_last_save`` / ``_dirty`` /
    ``_atexit_registered`` attributes initialised in the registry's
    ``__init__``.
    """

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
                        cost_usd=float(rec_data.get("cost_usd", 0.0)),
                        last_block_kind=str(rec_data.get("last_block_kind", "")),
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
