"""Regression tests for the shared tier-ranking primitive.

These lock in the two bugs this module was extracted to fix, plus the
cost-awareness that the per-page x402 price cannot express:

1. A single lucky sample used to beat a proven tier (raw ratio scoring).
2. ``best_tier`` and ``reorder_for_domain`` used different eligibility rules,
   so the "best" tier was not even the head of the ranked ladder.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from dataclasses import dataclass, field

from pry.engine import tier_score
from pry.engine.resilience import DomainTierMemory, ResilienceRegistry, TierRecord

NOW = 1_800_000_000.0
LADDER = ["fetch", "js_render", "flaresolverr", "browser"]


@dataclass
class FakeTier:
    successes: int = 0
    failures: int = 0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    total_latency: float = 0.0
    cost_usd: float = 0.0
    extra: dict[str, str] = field(default_factory=dict)


def test_lucky_single_sample_cannot_outrank_a_proven_tier() -> None:
    """Bug 1: raw ratio scoring let 1/1 (score 1.0) beat 98/100 (0.98)."""
    lucky = FakeTier(successes=1, failures=0, last_success_at=NOW)
    proven = FakeTier(successes=98, failures=2, last_success_at=NOW)
    assert tier_score.utility(proven, NOW) > tier_score.utility(lucky, NOW)


def test_smoothed_rate_is_uninformative_without_samples() -> None:
    assert tier_score.smoothed_success_rate(0, 0) == 0.5


def test_cost_breaks_a_tie_between_equally_reliable_tiers() -> None:
    """The differentiator the vendors structurally cannot offer."""
    cheap = FakeTier(successes=50, failures=0, last_success_at=NOW, cost_usd=0.0)
    pricey = FakeTier(successes=50, failures=0, last_success_at=NOW, cost_usd=0.05)
    assert tier_score.utility(cheap, NOW) > tier_score.utility(pricey, NOW)


def test_latency_penalty_is_bounded_and_free_when_unused() -> None:
    assert tier_score.latency_penalty(0.0, 0) == 0.0
    assert tier_score.latency_penalty(10_000_000.0, 10) == 1.0


def test_recency_decays_to_zero_beyond_the_half_life() -> None:
    assert tier_score.recency_bonus(0.0, NOW) == 0.0
    assert tier_score.recency_bonus(NOW - 1.0, NOW) == 1.0
    long_ago = (
        NOW - tier_score.RECENCY_FULL_BONUS_SECONDS - 40 * tier_score.RECENCY_HALF_LIFE_SECONDS
    )
    assert tier_score.recency_bonus(long_ago, NOW) < 1e-9


def test_rank_tiers_never_returns_empty_when_all_are_skipped() -> None:
    """A chronic failure outside the cooldown window is dropped, not cooled."""
    old = NOW - 10 * tier_score.RECENCY_HALF_LIFE_SECONDS
    chronic = {"fetch": FakeTier(successes=0, failures=50, last_failure_at=old)}
    ordered = tier_score.rank_tiers(LADDER, chronic, now=NOW)
    # fetch is genuinely dropped; the unrecorded rungs keep their static order
    assert "fetch" not in ordered
    expected = ["js_render", "flaresolverr", "browser"]
    assert ordered == expected


def test_rank_tiers_falls_back_to_the_static_ladder_when_all_are_chronic() -> None:
    """The scraper must always have a next rung, even if every rung is bad."""
    old = NOW - 10 * tier_score.RECENCY_HALF_LIFE_SECONDS
    chronic = {tier: FakeTier(successes=0, failures=50, last_failure_at=old) for tier in LADDER}
    assert tier_score.rank_tiers(LADDER, chronic, now=NOW) == LADDER


def test_rank_tiers_passes_through_when_nothing_is_known() -> None:
    assert tier_score.rank_tiers(LADDER, {}, now=NOW) == LADDER


def test_rank_tiers_demotes_a_recent_failure_without_dropping_it() -> None:
    records = {"fetch": FakeTier(successes=20, failures=1, last_failure_at=NOW - 10)}
    ordered = tier_score.rank_tiers(LADDER, records, now=NOW)
    assert ordered[-1] == "fetch"
    assert set(ordered) == set(LADDER)


def test_best_tier_agrees_with_the_head_of_the_ranked_ladder() -> None:
    """Bug 2: the two readers used different eligibility rules."""
    memory = DomainTierMemory()
    for _ in range(6):
        memory.record("example.com", "js_render", True, 120.0)
    for _ in range(3):
        memory.record("example.com", "fetch", True, 30.0)
        memory.record("example.com", "browser", False, 900.0, block_kind="cloudflare")
    memory.record("example.com", "flaresolverr", False, 800.0, block_kind="captcha")
    memory.record("example.com", "flaresolverr", False, 800.0)
    memory.record("example.com", "flaresolverr", False, 800.0)

    best = memory.best_tier("example.com", LADDER)
    ranked = memory.reorder_for_domain("example.com", LADDER)
    assert best is not None
    assert ranked[0] == best
    # chronic failures are gone from the ladder entirely
    assert "flaresolverr" not in ranked


def test_best_tier_is_none_when_nothing_has_ever_succeeded() -> None:
    memory = DomainTierMemory()
    memory.record("example.com", "fetch", False, 10.0)
    assert memory.best_tier("example.com", LADDER) is None


def test_record_round_trips_cost_and_block_kind() -> None:
    memory = DomainTierMemory()
    memory.record("example.com", "browser", False, 900.0, cost_usd=0.02, block_kind="cloudflare")
    rec: TierRecord = memory.data["example.com"]["browser"]
    assert rec.cost_usd == 0.02
    assert rec.last_block_kind == "cloudflare"
    assert rec.successes == 0

    registry = ResilienceRegistry()
    registry._restore_state({"domain_memory": memory.to_dict()})
    again: TierRecord = registry.domain_memory.data["example.com"]["browser"]
    assert again.cost_usd == 0.02
    assert again.last_block_kind == "cloudflare"
