"""Warm the in-process tier memory from Postgres — the read path.

The hot cache (:class:`~pry.engine.resilience_domain_memory.DomainTierMemory`)
is what ``tier_score.rank_tiers`` reads on the scrape path; this module is the
only thing that pushes durable DB counters into it, and it does so
*additively*:

    seed = prior_from_catalog + stored_from_db

so a record that already has in-process evidence is **never** overwritten by
stale DB numbers. That is the whole degradation story in one sentence: if this
module is never called, or the DB is down and :func:`warm_domain_from_db`
returns 0, the ranking is exactly what it was before this change.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from pry.engine.method_stats_store import MethodStatsStore
    from pry.engine.resilience_domain_memory import DomainTierMemory

logger = logging.getLogger(__name__)

__all__ = ["seed_from_catalog", "warm_domain_from_db", "warm_domains"]


def warm_domain_from_db(
    memory: DomainTierMemory,
    store: MethodStatsStore,
    domain: str,
) -> int:
    """Merge ``domain``'s stored counters into ``memory``. Returns rows applied.

    Non-fatal: a store that raises is logged and treated as "nothing stored",
    so the caller never has to guard. Records already present in ``memory``
    win — see the module docstring.
    """
    try:
        rows = store.load_domain(domain)
    except (
        OSError,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
        RuntimeError,
        SQLAlchemyError,
    ) as e:  # a warm-up failure must not break ranking
        logger.debug("tier_memory_warm_failed", extra={"error": f"{type(e).__name__}: {e}"[:120]})
        return 0
    return seed_from_catalog(memory, domain, rows)


def warm_domains(
    memory: DomainTierMemory,
    store: MethodStatsStore,
    domains: list[str],
) -> int:
    """Warm several domains. Returns the total number of rows applied."""
    return sum(warm_domain_from_db(memory, store, d) for d in domains)


def seed_from_catalog(
    memory: DomainTierMemory,
    domain: str,
    rows: list[dict[str, Any]],
) -> int:
    """Apply stored counters for one domain. Pure — no DB access, no I/O.

    ``rows`` is the :meth:`MethodStatsStore.load_domain` shape. Kept separate
    from :func:`warm_domain_from_db` so the merge arithmetic is testable
    without a database.
    """
    applied = 0
    for row in rows:
        method = str(row.get("method") or "")
        if not method:
            continue
        attempts = _int(row.get("attempts"))
        wins = min(_int(row.get("wins")), attempts)
        if attempts <= 0:
            continue
        applied += 1
        existing = memory.data[domain].get(method)
        if existing is not None and (existing.successes + existing.failures) > 0:
            # In-process evidence is fresher than the table. Add only the gap
            # so a warm-up never double-counts or rolls the record backwards.
            _backfill_gap(existing, attempts, wins, row)
            continue
        memory.data[domain][method] = _to_record(row, attempts, wins)
    return applied


def _to_record(row: dict[str, Any], attempts: int, wins: int) -> Any:
    """Build a fresh ``TierRecord`` from a stored row.

    The stored p50 is used as the ``total_latency`` proxy: the in-process
    record keeps a sum and divides by successes inside
    :func:`tier_score.latency_penalty`, so feeding it ``mean_ms * successes``
    reproduces the same penalty the DB row implies.
    """
    from pry.engine.resilience_domain_memory import TierRecord

    seen_at = _int(row.get("last_seen_at"))
    p50_ms = _float(row.get("latency_p50_ms"))
    return TierRecord(
        successes=wins,
        failures=max(0, attempts - wins),
        last_success_at=float(seen_at),
        last_failure_at=0.0,
        total_latency=(p50_ms / 1000.0) * wins,
        cost_usd=_float(row.get("cost_usd_total")),
        last_block_kind=str(row.get("last_block_kind") or ""),
    )


def _backfill_gap(existing: Any, attempts: int, wins: int, row: dict[str, Any]) -> None:
    """Top up an in-process record with only what it is missing."""
    have = existing.successes + existing.failures
    if attempts <= have:
        return
    p50_ms = _float(row.get("latency_p50_ms"))
    seen_at = float(_int(row.get("last_seen_at")))
    extra = attempts - have
    extra_wins = max(0, min(wins - existing.successes, extra))
    existing.failures += extra - extra_wins
    existing.successes += extra_wins
    existing.total_latency += (p50_ms / 1000.0) * extra_wins
    existing.cost_usd += _float(row.get("cost_usd_total"))
    if extra_wins and not existing.last_block_kind:
        existing.last_block_kind = str(row.get("last_block_kind") or "")
    if seen_at > 0:
        existing.last_success_at = max(existing.last_success_at, seen_at)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0
