"""Pry - SQLAlchemy models: resilience (learned per-domain method memory).

Durable home for the counters behind
:class:`~pry.engine.resilience_domain_memory.DomainTierMemory`. Before this
table the learned "which method works on this domain" intelligence lived only
in the process (plus an optional JSON snapshot), so a restart forgot
everything. ``domain_method_stats`` makes the memory survive restarts and
makes it queryable across workers.

The table is deliberately *aggregate* — one row per (domain, method) holding
running counters, not an event log. The in-process ``DomainTierMemory`` stays
the hot cache: the write path batches here in the background and a read
failure is invisible to the scraper.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# pyright: basic
from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy resolves Mapped[] at runtime

from pry.core.db.models_base import Base, _now

if Base is not None:
    from sqlalchemy import DateTime, Float, Index, Integer, String
    from sqlalchemy.orm import Mapped, mapped_column

    __all__ = ["IX_DOMAIN_METHOD_STATS_DOMAIN_WINS", "DomainMethodStat"]

    # Hot lookup: the read path asks "which methods have worked on this
    # domain, best first" — always scoped to one domain. Composite PK already
    # covers (domain, method); this serves the domain-prefixed, wins-ordered
    # ranking query without a sort.
    IX_DOMAIN_METHOD_STATS_DOMAIN_WINS = "ix_domain_method_stats_domain_wins"

    class DomainMethodStat(Base):
        """Running per-(domain, method) scrape-outcome counters.

        Column semantics, and how each maps back onto the in-process
        :class:`~pry.engine.resilience_domain_memory.TierRecord`:

        ==================  ===================================================
        column              meaning
        ==================  ===================================================
        ``attempts``        ``successes + failures``
        ``wins``            ``successes``
        ``latency_p50_ms``  median of the recorded latencies, milliseconds
        ``latency_p95_ms``  95th percentile of the recorded latencies
        ``cost_usd_total``  ``cost_usd`` — cumulative marginal cost, USD
        ``last_block_kind`` last ``BlockSignal.kind`` seen (diagnostics; never
                            treated as a win)
        ``last_seen_at``    last attempt, success or failure
        ==================  ===================================================

        ``attempts - wins`` is the failure count, and
        ``latency_p95_ms - latency_p50_ms`` is the latency spread — so no
        redundant success/failure/total-latency columns are stored.
        """

        __tablename__ = "domain_method_stats"
        __table_args__ = (Index(IX_DOMAIN_METHOD_STATS_DOMAIN_WINS, "domain", "wins"),)

        domain: Mapped[str] = mapped_column(String(255), primary_key=True)
        method: Mapped[str] = mapped_column(String(64), primary_key=True)
        attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
        wins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
        latency_p50_ms: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
        latency_p95_ms: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
        cost_usd_total: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
        last_block_kind: Mapped[str] = mapped_column(String(32), default="", server_default="")
        last_seen_at: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
        updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
