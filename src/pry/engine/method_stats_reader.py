"""Read half of the ``domain_method_stats`` store.

One function, one job: fetch the stored counters for a single domain. The
result feeds :func:`pry.engine.tier_memory_db.warm_domain_from_db`, which
seeds the in-process hot cache that ``tier_score.rank_tiers`` actually reads —
so a failure here is a cache miss, never a broken scrape.

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
    from collections.abc import Callable

    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

__all__ = ["ROW_FIELDS", "load_domain_stats", "to_row"]


def load_domain_stats(
    domain: str,
    *,
    fail: Callable[[BaseException], None],
) -> list[dict[str, Any]]:
    """Counters for ``domain``, best-first. Never raises; ``[]`` on error.

    Ordering is ``wins DESC, method`` so the caller gets the useful rows first
    and the tie-break is deterministic. That is the ``(domain, wins)`` index
    doing its job — a bare ``WHERE domain = ?`` would need a sort.
    """
    try:
        from sqlalchemy import select

        from pry.core.db.models_resilience import DomainMethodStat
        from pry.core.db.session import session_scope

        with session_scope() as session:
            stmt = (
                select(DomainMethodStat)
                .where(DomainMethodStat.domain == domain)
                .order_by(DomainMethodStat.wins.desc(), DomainMethodStat.method)
            )
            return [to_row(r) for r in session.execute(stmt).scalars()]
    except (
        OSError,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
        RuntimeError,
        SQLAlchemyError,
    ) as e:  # a cold or dead database is a cache miss, never a crash
        fail(e)
        logger.debug(
            "domain_method_stats_read_failed",
            extra={"domain": domain[:80], "error": f"{type(e).__name__}"},
        )
        return []


# The exact contract tier_memory_db.seed_from_catalog consumes. Named once so
# the two modules cannot drift apart silently.
ROW_FIELDS = (
    "method",
    "attempts",
    "wins",
    "latency_p50_ms",
    "latency_p95_ms",
    "cost_usd_total",
    "last_block_kind",
    "last_seen_at",
)


def to_row(record: Any, _session: Session | None = None) -> dict[str, Any]:
    """ORM row -> plain dict, coercing NULLs so the caller never sees None."""
    return {
        "method": record.method,
        "attempts": int(record.attempts or 0),
        "wins": int(record.wins or 0),
        "latency_p50_ms": float(record.latency_p50_ms or 0.0),
        "latency_p95_ms": float(record.latency_p95_ms or 0.0),
        "cost_usd_total": float(record.cost_usd_total or 0.0),
        "last_block_kind": record.last_block_kind or "",
        "last_seen_at": int(record.last_seen_at or 0),
    }
