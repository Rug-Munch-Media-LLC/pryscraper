"""Tests for the per-tier cost model and its wiring into the write path.

The P0 ranking fix added ``cost_usd`` and ``last_block_kind`` to the memory
record, but nothing supplied them: in production ``cost_penalty()`` always
returned 0.0, so the cost term was dead weight and ``last_block_kind`` was
always empty. These tests assert the producer side is now connected.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from pry.engine import tier_cost
from pry.engine.resilience import ResilienceRegistry


def test_free_tiers_cost_nothing(monkeypatch: Any) -> None:
    monkeypatch.delenv(tier_cost.PREMIUM_COST_ENV, raising=False)
    for tier in ("direct", "playwright", "flaresolverr", "tor", "google_cache"):
        assert tier_cost.tier_cost(tier) == 0.0
        assert tier_cost.is_cost_known(tier) is True


def test_premium_proxy_is_unknown_until_priced(monkeypatch: Any) -> None:
    monkeypatch.delenv(tier_cost.PREMIUM_COST_ENV, raising=False)
    assert tier_cost.tier_cost("premium_proxy") == 0.0
    assert tier_cost.is_cost_known("premium_proxy") is False


def test_configured_premium_price_is_used(monkeypatch: Any) -> None:
    monkeypatch.setenv(tier_cost.PREMIUM_COST_ENV, "0.05")
    assert tier_cost.premium_proxy_cost_usd() == 0.05
    assert tier_cost.tier_cost("premium_proxy") == 0.05
    assert tier_cost.is_cost_known("premium_proxy") is True


def test_a_malformed_price_is_unknown_not_free(monkeypatch: Any) -> None:
    """A typo must not silently make the paid rung look free."""
    monkeypatch.setenv(tier_cost.PREMIUM_COST_ENV, "five cents")
    assert tier_cost.tier_cost("premium_proxy") == 0.0
    assert tier_cost.is_cost_known("premium_proxy") is False


def test_a_negative_price_is_rejected(monkeypatch: Any) -> None:
    monkeypatch.setenv(tier_cost.PREMIUM_COST_ENV, "-1")
    assert tier_cost.premium_proxy_cost_usd() == 0.0
    assert tier_cost.is_cost_known("premium_proxy") is False


def test_expensive_tier_is_demoted_over_a_free_one(monkeypatch: Any) -> None:
    """The end-to-end payoff: same success rate, different cost."""
    monkeypatch.setenv(tier_cost.PREMIUM_COST_ENV, "0.05")
    registry = ResilienceRegistry()
    for _ in range(8):
        registry.record_domain_tier_result("example.com", "direct", True, 200.0)
        registry.record_domain_tier_result(
            "example.com", "premium_proxy", True, 900.0, cost_usd=0.05
        )
    order = registry.reorder_for_domain("example.com", ["direct", "premium_proxy"])
    assert order[0] == "direct"


def test_block_kind_reaches_the_memory_through_the_registry() -> None:
    registry = ResilienceRegistry()
    registry.record_domain_tier_result(
        "blocked.example", "playwright", False, 900.0, block_kind="cloudflare"
    )
    rec = registry.domain_memory.data["blocked.example"]["playwright"]
    assert rec.last_block_kind == "cloudflare"
    assert rec.successes == 0
    assert rec.failures == 1
