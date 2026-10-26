"""Pure ordering and staleness arithmetic for the unlock ledger.

No I/O and no clock reads: the caller passes ``now`` so ranking is a pure
function of the records. Kept separate from the store so the ordering rules and
the SQL can be tested independently.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from dataclasses import dataclass

# Relative cost of a method, cheapest first. Index doubles as the tie-break.
METHOD_COST: dict[str, int] = {
    "http": 0,
    "api_endpoint": 1,
    "headers": 2,
    "wait_selector": 3,
    "js_render": 4,
    "proxy": 5,
    "flaresolverr": 6,
}
# Ordinary fetching knobs: replayable without a human in the loop.
BASELINE_METHODS: frozenset[str] = frozenset({"http", "api_endpoint", "headers", "wait_selector"})
# Circumvention-shaped: recorded on discovery, replayed only after approval.
BYPASS_METHODS: frozenset[str] = frozenset({"js_render", "proxy", "flaresolverr"})
# Trial ladder tried in order when a domain has no usable approved recipe.
DEFAULT_METHODS: tuple[str, ...] = ("http", "api_endpoint", "headers", "js_render", "flaresolverr")

STALE_AFTER_FAILURES = 3
RECENT_WINDOW_SECONDS = 86_400.0

__all__ = [
    "BASELINE_METHODS",
    "BYPASS_METHODS",
    "DEFAULT_METHODS",
    "METHOD_COST",
    "RECENT_WINDOW_SECONDS",
    "STALE_AFTER_FAILURES",
    "MethodRecord",
    "order_candidates",
    "replay_order",
]


@dataclass(frozen=True, slots=True)
class MethodRecord:
    """One ``(domain, method)`` row, as the ranking sees it."""

    domain: str
    method: str
    params: dict[str, object]
    selector: str
    last_ok_at: float | None
    ok_count: int
    fail_count: int
    fail_streak: int
    latency_ms: float
    notes: str
    approved: bool = True

    @property
    def cost(self) -> int:
        """Lower is cheaper to retry."""
        return METHOD_COST.get(self.method, 99)

    @property
    def is_stale(self) -> bool:
        """True once the recipe has failed ``STALE_AFTER_FAILURES`` times running."""
        return self.fail_streak >= STALE_AFTER_FAILURES

    def recently_worked(self, now: float) -> bool:
        """True if it succeeded inside the recency window and has not since rotted."""
        return (
            self.last_ok_at is not None
            and (now - self.last_ok_at) <= RECENT_WINDOW_SECONDS
            and not self.is_stale
        )

    def rank_key(self, now: float) -> tuple[int, int, int, str]:
        """Total, deterministic order: fresh+working, then working, then stale."""
        tier = 0 if self.recently_worked(now) else (2 if self.is_stale else 1)
        return (tier, -self.ok_count, self.cost, self.method)


def replay_order(records: list[MethodRecord], now: float) -> list[str]:
    """Approved methods that have actually succeeded, best first. The replay path.

    A record with no win behind it is not a recipe — it is a failure the repair
    path has already tried — so it is never replayed.
    """
    usable = (r for r in records if r.approved and r.ok_count > 0)
    return [r.method for r in sorted(usable, key=lambda r: r.rank_key(now))]


def order_candidates(records: list[MethodRecord], now: float) -> list[str]:
    """Approved methods best-first, then the untouched defaults as trials."""
    ordered = replay_order(records, now)
    return ordered + [m for m in DEFAULT_METHODS if m not in ordered]
