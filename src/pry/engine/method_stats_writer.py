"""Batched, non-fatal writer for the ``domain_method_stats`` table.

Split out of :mod:`pry.engine.method_stats_store` to keep each module inside
the repo's 200-line policy. This half owns the write path and nothing else —
one buffered background flush, no SQL knowledge beyond insert-or-accumulate.

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
import threading
import time
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from pry.engine.method_stats_rollup import accumulate_row

logger = logging.getLogger(__name__)

# Flush cadence and buffer ceiling. 250ms keeps the table roughly current
# without a query per scrape; the cap bounds memory if the flusher wedges.
FLUSH_INTERVAL_SECONDS = 0.25
MAX_BUFFERED_UPDATES = 500
# Per-key slice held before the oldest half is dropped, so a permanently
# failing flush cannot grow the buffer without bound.
MAX_UPDATES_PER_KEY = 256

__all__ = [
    "FLUSH_INTERVAL_SECONDS",
    "MAX_BUFFERED_UPDATES",
    "MethodStatUpdate",
    "MethodStatsWriter",
]


@dataclass(frozen=True, slots=True)
class MethodStatUpdate:
    """One pending (domain, method) counter increment.

    ``win`` makes this a delta rather than a snapshot, so two processes racing
    on the same key both land instead of one overwriting the other.
    """

    domain: str
    method: str
    win: bool
    latency_ms: float
    cost_usd: float
    block_kind: str
    seen_at: float


class MethodStatsWriter:
    """Buffer outcomes here; a daemon thread writes them out in batches."""

    def __init__(
        self,
        *,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
        max_buffered: int = MAX_BUFFERED_UPDATES,
    ) -> None:
        self._flush_interval = flush_interval
        self._max_buffered = max_buffered
        self._lock = threading.Lock()
        self._buffer: dict[tuple[str, str], list[MethodStatUpdate]] = {}
        self._last_flush = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.consecutive_failures = 0
        self.last_error = ""

    # ── hot path ─────────────────────────────────────────────────────────

    def record(
        self,
        domain: str,
        method: str,
        *,
        win: bool,
        latency_ms: float = 0.0,
        cost_usd: float = 0.0,
        block_kind: str = "",
    ) -> None:
        """Buffer one outcome. Returns immediately — no DB, no I/O, no raise.

        Called from ``scraper_orchestrate._record_tier_outcome`` on the scrape
        path, so its cost is the only thing that matters here.
        """
        if not domain or not method:
            return
        update = MethodStatUpdate(
            domain=domain,
            method=method,
            win=win,
            latency_ms=max(0.0, latency_ms),
            cost_usd=max(0.0, cost_usd),
            block_kind=block_kind,
            seen_at=time.time(),
        )
        with self._lock:
            bucket = self._buffer.setdefault((domain, method), [])
            bucket.append(update)
            if len(bucket) > MAX_UPDATES_PER_KEY:
                del bucket[: len(bucket) // 2]  # drop the oldest half
            over = sum(len(v) for v in self._buffer.values()) > self._max_buffered
        if over:
            self.flush()
        self._ensure_worker()

    def start(self) -> None:
        """Start the background flusher (idempotent)."""
        self._ensure_worker()

    def flush(self, *, force: bool = True) -> int:
        """Write the buffer out. Returns rows written (0 on failure).

        ``force=False`` is a no-op until the flush interval has elapsed.
        """
        with self._lock:
            if not self._buffer:
                return 0
            if not force and (time.monotonic() - self._last_flush) < self._flush_interval:
                return 0
            pending = self._buffer
            self._buffer = {}
            self._last_flush = time.monotonic()
        return self._write(pending)

    def buffered_keys(self) -> int:
        with self._lock:
            return len(self._buffer)

    def fail(self, exc: BaseException) -> None:
        """Record a swallowed database failure (shared with the read half)."""
        self.consecutive_failures += 1
        self.last_error = f"{type(exc).__name__}: {exc}"[:200]
        logger.debug("domain_method_stats_db_unavailable", extra={"error": self.last_error})

    def stop(self, *, drain: bool = True) -> None:
        """Stop the flusher. ``drain=True`` writes what is buffered first."""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if drain:
            self.flush()
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._flush_interval * 4)

    def worker_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── internals ────────────────────────────────────────────────────────

    def _write(self, pending: dict[tuple[str, str], list[MethodStatUpdate]]) -> int:
        """One transaction for the whole batch. Never raises."""
        try:
            from pry.core.db.models_resilience import DomainMethodStat
            from pry.core.db.session import session_scope

            with session_scope() as session:
                for (domain, method), updates in pending.items():
                    accumulate_row(session, DomainMethodStat, domain, method, updates)
        except (
            OSError,
            TypeError,
            ValueError,
            AttributeError,
            KeyError,
            RuntimeError,
            SQLAlchemyError,
        ) as e:  # a DB outage must never break a scrape
            self.fail(e)
            logger.debug("domain_method_stats_write_failed", extra={"rows": len(pending)})
            return 0
        self.consecutive_failures = 0
        self.last_error = ""
        return len(pending)

    def _ensure_worker(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pry-method-stats", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._flush_interval):
            self.flush()
