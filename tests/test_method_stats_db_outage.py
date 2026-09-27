"""The degradation contract: a database outage must not break scrapes.

The behaviour these pin down is the reason the whole store is fire-and-forget:
``record`` cannot raise, ``flush`` returns 0, ``load_domain`` returns ``[]``,
and the in-process ranking is untouched.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError

from pry.engine.method_stats_store import MethodStatsStore
from pry.engine.resilience_domain_memory import DomainTierMemory

if TYPE_CHECKING:
    import pytest


def test_write_failure_is_swallowed_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead database must cost durability, not the scrape."""
    import pry.core.db.session as session_mod

    def boom() -> Any:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(session_mod, "session_scope", boom)
    store = MethodStatsStore(flush_interval=60.0)
    store.record("a.com", "m", win=True, latency_ms=5.0)
    assert store.flush() == 0
    assert store.stats()["consecutive_failures"] == 1
    assert "OperationalError" in store.stats()["last_error"]
    store.stop(drain=False)


def test_read_failure_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pry.core.db.session as session_mod

    def boom() -> Any:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(session_mod, "session_scope", boom)
    store = MethodStatsStore(flush_interval=60.0)
    assert store.load_domain("a.com") == []
    assert store.stats()["consecutive_failures"] == 1
    store.stop(drain=False)


def test_record_never_raises_when_store_is_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scrape-path guarantee: record() cannot propagate a DB failure."""
    import pry.core.db.session as session_mod

    monkeypatch.setattr(
        session_mod,
        "session_scope",
        lambda: (_ for _ in ()).throw(OperationalError("no database")),
    )
    memory = DomainTierMemory(store=MethodStatsStore(flush_interval=60.0))
    memory.record("a.com", "fetch", True, 0.2, cost_usd=0.01)  # must not raise
    assert memory.data["a.com"]["fetch"].successes == 1
    memory.store.stop(drain=False)


def test_memory_without_store_records_locally() -> None:
    memory = DomainTierMemory()
    memory.record("a.com", "fetch", True, 0.1)
    assert memory.data["a.com"]["fetch"].successes == 1
    assert memory.store is None


# ── seeding the hot cache (read path → rank_tiers) ───────────────────────

# (seed-from-table behaviour lives in test_method_stats_seed.py)
