"""Tests for the durable domain_method_stats store and its read path.

Covers the contract that matters operationally: writes are batched and never
raise, and a database that is unreachable degrades to in-process memory
instead of breaking scrapes.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import create_engine

from pry.core.db.models_resilience import DomainMethodStat
from pry.engine.method_stats_store import MethodStatsStore, MethodStatUpdate

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def sqlite_db(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Point the engine at a throwaway SQLite file and create the table.

    SQLite (not Postgres) so the suite stays hermetic; the store only uses
    portable ORM calls, and the Postgres-specific bits are the migration, which
    ``scripts/check_migrations.py`` already exercises end to end.
    """
    from sqlalchemy.orm import Session

    import pry.core.db.session as session_mod
    from pry.core.db.models_base import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'stats.db'}", future=True)
    Base.metadata.create_all(engine, tables=[DomainMethodStat.__table__])

    @contextmanager
    def scope() -> Iterator[Any]:
        s = Session(bind=engine)
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(session_mod, "get_engine", lambda: engine)
    monkeypatch.setattr(session_mod, "session_scope", scope)
    yield engine
    engine.dispose()


# ── write path ───────────────────────────────────────────────────────────


def test_record_buffers_and_never_touches_db() -> None:
    """record() must not open a session — that is the whole no-block guarantee."""
    store = MethodStatsStore(flush_interval=60.0)
    store.record(
        MethodStatUpdate(
            domain="example.com", method="fetch", win=True, latency_ms=120.0, cost_usd=0.001
        )
    )
    assert store.stats()["buffered_keys"] == 1
    store.stop(drain=False)


def test_record_ignores_empty_identifiers() -> None:
    store = MethodStatsStore(flush_interval=60.0)
    store.record(MethodStatUpdate(domain="", method="fetch", win=True))
    store.record(MethodStatUpdate(domain="example.com", method="", win=True))
    assert store.stats()["buffered_keys"] == 0
    store.stop(drain=False)


def test_flush_batches_all_outcomes_into_one_row(sqlite_db: Any) -> None:
    from sqlalchemy.orm import Session

    store = MethodStatsStore(flush_interval=60.0)
    for i in range(4):
        store.record(
            MethodStatUpdate(
                domain="example.com",
                method="fetch",
                win=i < 3,
                latency_ms=100.0 + i,
                cost_usd=0.001,
                block_kind="captcha" if i == 3 else "",
            )
        )
    assert store.flush() == 1

    with Session(sqlite_db) as s:
        row = s.get(DomainMethodStat, ("example.com", "fetch"))
    assert row is not None
    expected = (4, 3)
    assert (row.attempts, row.wins) == expected
    assert row.cost_usd_total == pytest.approx(0.004)
    assert row.last_block_kind == "captcha"
    assert row.latency_p50_ms > 0
    assert row.latency_p95_ms >= row.latency_p50_ms
    assert row.last_seen_at > 0
    store.stop(drain=False)


def test_repeated_flush_accumulates_rather_than_resets(sqlite_db: Any) -> None:
    from sqlalchemy.orm import Session

    store = MethodStatsStore(flush_interval=60.0)
    store.record(
        MethodStatUpdate(domain="a.com", method="m", win=True, latency_ms=10.0, cost_usd=0.5)
    )
    store.flush()
    store.record(
        MethodStatUpdate(domain="a.com", method="m", win=False, latency_ms=20.0, cost_usd=0.5)
    )
    store.flush()

    with Session(sqlite_db) as s:
        row = s.get(DomainMethodStat, ("a.com", "m"))
    assert row is not None
    expected = (2, 1)
    assert (row.attempts, row.wins) == expected
    assert row.cost_usd_total == pytest.approx(1.0)
    store.stop(drain=False)


def test_flush_under_interval_is_a_noop() -> None:
    store = MethodStatsStore(flush_interval=60.0)
    store.record(MethodStatUpdate(domain="a.com", method="m", win=True))
    store.flush()  # first flush arms the interval
    store.record(MethodStatUpdate(domain="a.com", method="m", win=True))
    assert store.flush(force=False) == 0
    store.stop(drain=False)


# ── read path ────────────────────────────────────────────────────────────


def test_load_domain_orders_by_wins(sqlite_db: Any) -> None:
    store = MethodStatsStore(flush_interval=60.0)
    for method, wins in (("cheap", 1), ("browser", 5)):
        for _ in range(wins):
            store.record(MethodStatUpdate(domain="a.com", method=method, win=True, latency_ms=50.0))
    store.flush()

    rows = store.load_domain("a.com")
    expected = ["browser", "cheap"]
    assert [r["method"] for r in rows] == expected
    assert rows[0]["wins"] == 5
    store.stop(drain=False)


def test_load_domain_unknown_returns_empty(sqlite_db: Any) -> None:
    store = MethodStatsStore(flush_interval=60.0)
    assert store.load_domain("never-seen.com") == []
    store.stop(drain=False)
