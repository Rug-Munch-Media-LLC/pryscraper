"""Order-statistic arithmetic for the durable method-memory store.

Split out of :mod:`pry.engine.method_stats_store` so the batch-rollup math can
be unit-tested on its own, and so the store module stays inside the repo's
200-line-per-file policy. Pure functions, no I/O, no SQLAlchemy.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session

    from pry.engine.method_stats_writer import MethodStatUpdate

__all__ = ["accumulate_row", "collapse_updates", "merge_percentile", "percentile_ms"]


def accumulate_row(
    session: Session,
    model: Any,
    domain: str,
    method: str,
    updates: list[MethodStatUpdate],
) -> None:
    """Insert-or-accumulate one ``(domain, method)`` row in ``session``.

    Increments, never overwrites: two processes racing on the same key both
    land. The caller owns the transaction, so a batch is all-or-nothing.
    """
    deltas = collapse_updates(updates)
    seen_at = int(max(u.seen_at for u in updates))
    row = session.get(model, (domain, method))
    if row is None:
        session.add(
            model(
                domain=domain,
                method=method,
                attempts=deltas["attempts"],
                wins=deltas["wins"],
                latency_p50_ms=deltas["p50"],
                latency_p95_ms=deltas["p95"],
                cost_usd_total=deltas["cost"],
                last_block_kind=deltas["block"],
                last_seen_at=seen_at,
            )
        )
        return
    row.attempts = (row.attempts or 0) + deltas["attempts"]
    row.wins = (row.wins or 0) + deltas["wins"]
    row.cost_usd_total = (row.cost_usd_total or 0.0) + deltas["cost"]
    row.latency_p50_ms = merge_percentile(row.latency_p50_ms, deltas["p50"])
    row.latency_p95_ms = merge_percentile(row.latency_p95_ms, deltas["p95"])
    if deltas["block"]:
        row.last_block_kind = deltas["block"]
    row.last_seen_at = max(int(row.last_seen_at or 0), seen_at)


def percentile_ms(samples: Iterable[float], q: float) -> float:
    """Nearest-rank percentile over ``samples`` (already in ms). 0.0 if empty.

    Nearest-rank rather than interpolating: the value has to be a latency that
    was actually observed, otherwise a stored p95 is not a claim anyone made.
    """
    values = sorted(v for v in samples if v >= 0)
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
    return float(values[idx])


def collapse_updates(updates: list[MethodStatUpdate]) -> dict[str, Any]:
    """Fold a batch of updates for one (domain, method) into a single delta.

    Returns ``attempts`` / ``wins`` / ``cost`` / ``p50`` / ``p95`` / ``block``.
    The block kind is the *last* non-empty one in the batch, matching the
    in-process ``TierRecord``, which overwrites on every blocked attempt.
    """
    latencies = [u.latency_ms for u in updates if u.latency_ms > 0]
    return {
        "attempts": len(updates),
        "wins": sum(1 for u in updates if u.win),
        "cost": sum(u.cost_usd for u in updates),
        "p50": percentile_ms(latencies, 0.5),
        "p95": percentile_ms(latencies, 0.95),
        "block": next((u.block_kind for u in reversed(updates) if u.block_kind), ""),
    }


def merge_percentile(stored: float | None, incoming: float) -> float:
    """Blend a stored percentile with a fresh one from the same population.

    Weighted 0.7/0.3 toward the stored value. Deliberately crude: one slow
    scrape batch must not be able to erase a month of evidence, and a month of
    evidence must not pin a percentile that just regressed. The ranking only
    uses latency as a bounded tie-break (see :mod:`pry.engine.tier_score`), so
    exactness buys nothing here.
    """
    base = float(stored or 0.0)
    if incoming <= 0:
        return base
    if base <= 0:
        return float(incoming)
    return (base * 0.7) + (incoming * 0.3)
