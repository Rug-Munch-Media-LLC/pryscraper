"""Per-domain unlock ledger: remember how a site was reached, then replay it.

One row per ``(domain, method)`` in SQLite, so the recipe survives a Postgres
outage. Two decision paths on top of :class:`pry.engine.unlock_store.UnlockStore`:

- :meth:`UnlockLedger.choose_method` — replay the best approved recipe. Returns
  ``None`` unless ``PRY_UNLOCK_LEDGER=1``; that flag check is the single wiring
  point into crawling.
- :meth:`UnlockLedger.repair` — try candidates in order, record each outcome,
  and refuse to replay a newly discovered bypass without human approval.

Secrets are redacted before disk; see ``docs/ADR-unlock-ledger.md``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pry.engine.unlock_policy import BASELINE_METHODS, order_candidates, replay_order
from pry.engine.unlock_store import UnlockStore, enabled, normalize_domain, scrub_params

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["RepairOutcome", "UnlockLedger", "enabled", "normalize_domain", "scrub_params"]


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    """Result of one repair walk."""

    domain: str
    winner: str | None
    tried: tuple[str, ...]
    needs_approval: bool


class UnlockLedger(UnlockStore):
    """Recipe memory with a replay path and a repair path."""

    def choose_method(self, domain: str) -> str | None:
        """Best approved recipe that has actually worked, or ``None``."""
        if not enabled():
            return None
        order = replay_order(self.records(domain), self._now())
        return order[0] if order else None

    def repair(self, domain: str, attempt: Callable[[str], tuple[bool, float]]) -> RepairOutcome:
        """Try candidates in order, record each outcome, stop at the first success."""
        tried: list[str] = []
        for method in order_candidates(self.records(domain), self._now()):
            ok, latency_ms = attempt(method)
            tried.append(method)
            self.record_result(domain, method, ok, latency_ms)
            if ok:
                return RepairOutcome(
                    normalize_domain(domain),
                    method,
                    tuple(tried),
                    needs_approval=not self._is_approved(domain, method),
                )
        return RepairOutcome(normalize_domain(domain), None, tuple(tried), needs_approval=False)

    def _is_approved(self, domain: str, method: str) -> bool:
        """Baseline knobs replay freely; a discovered bypass needs ``approve``."""
        if method in BASELINE_METHODS:
            return True
        return any(r.method == method and r.approved for r in self.records(domain))
