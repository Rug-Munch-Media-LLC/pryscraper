"""Postgres-backed durable store for the per-domain method memory.

One row per (domain, method) in ``domain_method_stats``. The public object is
:class:`MethodStatsStore`, a thin facade over two halves kept in their own
modules so both stay inside the 200-line policy:

- :mod:`pry.engine.method_stats_writer` — the buffered, background write path.
- :mod:`pry.engine.method_stats_reader` — the read path used to warm the cache.
- :mod:`pry.engine.method_stats_rollup` — the pure batch arithmetic.

Rules that matter operationally:

1. **A scrape never waits for the DB.** ``record`` only appends to an in-memory
   buffer and returns; the flush runs on a daemon thread with its own session,
   so ``scraper_orchestrate._record_tier_outcome`` cannot pay for the database.
2. **Failure is invisible.** Every DB error is swallowed and logged at debug,
   and the batch is dropped. A database outage degrades to in-process-only
   memory — exactly the behaviour from before this store existed.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from pry.engine.method_stats_reader import load_domain_stats
from pry.engine.method_stats_rollup import collapse_updates, merge_percentile, percentile_ms
from pry.engine.method_stats_writer import (
    FLUSH_INTERVAL_SECONDS,
    MAX_BUFFERED_UPDATES,
    MethodStatsWriter,
    MethodStatUpdate,
)

__all__ = [
    "FLUSH_INTERVAL_SECONDS",
    "MAX_BUFFERED_UPDATES",
    "MethodStatUpdate",
    "MethodStatsStore",
    "collapse_updates",
    "merge_percentile",
    "percentile_ms",
]


class MethodStatsStore(MethodStatsWriter):
    """Batched, non-fatal reader/writer for ``domain_method_stats``.

    Inherits the whole write surface (``record``/``flush``/``stop``) from
    :class:`~pry.engine.method_stats_writer.MethodStatsWriter` and adds the one
    read the ranking needs: the stored counters for a single domain.
    """

    def load_domain(self, domain: str) -> list[dict[str, Any]]:
        """Stored counters for ``domain``, best-first. ``[]`` on any error."""
        try:
            return load_domain_stats(domain, fail=self.fail)
        except (
            OSError,
            TypeError,
            ValueError,
            AttributeError,
            KeyError,
            RuntimeError,
            SQLAlchemyError,
        ) as e:  # cold start must not break ranking
            self.fail(e)
            return []

    def stats(self) -> dict[str, Any]:
        return {
            "buffered_keys": self.buffered_keys(),
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "worker_alive": self.worker_alive(),
        }
