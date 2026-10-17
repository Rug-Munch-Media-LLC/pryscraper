"""Seeding the hot cache from the durable table, and what it must never do.

The rule: live in-process evidence is never overwritten. A seeded prior can
only add to what this process has learned itself.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

import pytest

from pry.engine import tier_cost
from pry.engine.method_stats_store import MethodStatsStore
from pry.engine.method_stats_writer import MethodStatUpdate  # noqa: TC001 - used at runtime
from pry.engine.resilience_domain_memory import DomainTierMemory
from pry.engine.tier_memory_db import seed_from_catalog, warm_domain_from_db


def test_seed_from_catalog_creates_records() -> None:
    memory = DomainTierMemory()
    applied = seed_from_catalog(
        memory,
        "a.com",
        [
            {
                "method": "fetch",
                "attempts": 10,
                "wins": 8,
                "latency_p50_ms": 120.0,
                "cost_usd_total": 0.01,
                "last_block_kind": "",
                "last_seen_at": 1000,
            }
        ],
    )
    assert applied == 1
    rec = memory.data["a.com"]["fetch"]
    expected = (8, 2)
    assert (rec.successes, rec.failures) == expected
    assert rec.cost_usd == pytest.approx(0.01)
    # total_latency is seconds*successes so tier_score's mean is the p50.
    assert rec.total_latency == pytest.approx(0.12 * 8)


def test_seed_does_not_overwrite_live_in_process_evidence() -> None:
    memory = DomainTierMemory()
    memory.record("a.com", "fetch", True, 0.5)
    applied = seed_from_catalog(
        memory,
        "a.com",
        [{"method": "fetch", "attempts": 100, "wins": 1, "last_seen_at": 1000}],
    )
    assert applied == 1
    rec = memory.data["a.com"]["fetch"]
    # Live record had 1 attempt; the store has 100 → only the gap is added.
    assert rec.successes + rec.failures == 100


def test_seed_skips_zero_attempt_rows() -> None:
    memory = DomainTierMemory()
    assert seed_from_catalog(memory, "a.com", [{"method": "m", "attempts": 0}]) == 0
    assert seed_from_catalog(memory, "a.com", [{"method": "", "attempts": 5}]) == 0


def test_warm_domain_from_db_survives_a_broken_store() -> None:
    class Broken:
        def load_domain(self, domain: str) -> list[dict[str, Any]]:
            raise RuntimeError("db down")

    memory = DomainTierMemory()
    assert warm_domain_from_db(memory, Broken(), "a.com") == 0  # type: ignore[arg-type]
    expected = ["fetch"]
    assert memory.reorder_for_domain("a.com", ["fetch"]) == expected


def test_seeded_memory_drives_ranking() -> None:
    """The end-to-end read path: stored wins must reorder the ladder."""
    from pry.engine import tier_score

    memory = DomainTierMemory()
    seed_from_catalog(
        memory,
        "a.com",
        [
            {"method": "cheap", "attempts": 10, "wins": 9, "last_seen_at": 0},
            {"method": "browser", "attempts": 10, "wins": 1, "last_seen_at": 0},
        ],
    )
    # 1/10 is a chronic failure, so the ladder skips it entirely.
    expected = ["cheap"]
    assert memory.reorder_for_domain("a.com", ["cheap", "browser"]) == expected
    expected_2 = ["cheap"]
    assert tier_score.rank_tiers(["cheap", "browser"], memory.data["a.com"]) == expected_2
    assert memory.best_tier("a.com", ["cheap", "browser"]) == "cheap"


def test_scrape_entry_point_reaches_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire-level proof: _record_tier_outcome -> registry -> store.record.

    The single writer in ``scraper_orchestrate`` is the only place a scrape
    outcome is produced, so this is the path that must stay non-blocking.
    """
    from pry.engine.resilience import ResilienceRegistry
    from pry.engine.resilience_domain_memory import DomainTierMemory

    seen: list[tuple[str, str, dict[str, Any]]] = []

    class Spy(MethodStatsStore):
        def record(self, update: MethodStatUpdate) -> None:
            seen.append(
                (
                    update.domain,
                    update.method,
                    {
                        "win": update.win,
                        "latency_ms": update.latency_ms,
                        "cost_usd": update.cost_usd,
                        "block_kind": update.block_kind,
                    },
                )
            )
            super().record(update)

    memory = DomainTierMemory(store=Spy(flush_interval=60.0))
    registry = ResilienceRegistry(method_stats=False)
    registry.domain_memory = memory

    from pry.engine.scraper_orchestrate import ScrapeOrchestrator

    # A real ladder rung, and a PAID one, so the assertion proves the writer
    # forwards tier_cost() rather than a hardcoded zero.
    monkeypatch.setenv(tier_cost.PREMIUM_COST_ENV, "0.05")
    ScrapeOrchestrator._record_tier_outcome(
        object(),  # self is unused by the method
        registry,
        None,
        "example.com",
        "premium_proxy",
        False,
        0.42,
        block_kind="cloudflare",
    )
    expected = [
        (
            "example.com",
            "premium_proxy",
            {
                "win": False,
                "latency_ms": 420.0,
                "cost_usd": 0.05,
                "block_kind": "cloudflare",
            },
        )
    ]
    assert seen == expected
    memory.store.stop(drain=False)


def test_registry_exposes_warm_from_db() -> None:
    from pry.engine.resilience import ResilienceRegistry

    registry = ResilienceRegistry(method_stats=False)
    assert registry.method_stats is None
    assert registry.warm_from_db("a.com") == 0
    assert registry.stats()["method_stats"] is None
