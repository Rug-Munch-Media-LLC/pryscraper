"""Regression tests for the tier-memory freshness filter.

``DOMAIN_MEMORY_MAX_AGE_SECONDS`` was defined and documented but never
enforced: a tier whose last success was days ago kept the full smoothed ratio
and merely lost its recency bonus, so it stayed at the head of the ladder and
kept being paid for. Old evidence is not weak evidence — past the bound a
record is dropped from the ranking entirely.

Covers the primitive (:func:`tier_score.rank_tiers`) and the reader that
inherits it (``DomainTierMemory.best_tier`` / ``reorder_for_domain``).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import time
from dataclasses import dataclass

from pry.engine import tier_score
from pry.engine.resilience_domain_memory import (
    DOMAIN_MEMORY_MAX_AGE_SECONDS,
    DomainTierMemory,
    TierRecord,
)

NOW = 1_800_000_000.0
DAY = 86_400.0
LADDER = ["fetch", "js_render", "flaresolverr", "browser"]


@dataclass
class FakeTier:
    successes: int = 0
    failures: int = 0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    total_latency: float = 0.0
    cost_usd: float = 0.0


def _ancient(age_days: float = 3.0) -> FakeTier:
    """A record that WAS excellent, three days ago."""
    return FakeTier(
        successes=100,
        failures=0,
        last_success_at=NOW - age_days * DAY,
        total_latency=100.0,
    )


# ── The bound is enforced ────────────────────────────────────────────────────


def test_ancient_record_is_not_promoted() -> None:
    """A proven tier that last worked days ago loses its claim to the front."""
    records = {"browser": _ancient()}
    fresh = tier_score.rank_tiers(LADDER, records, now=NOW)
    assert fresh.index("browser") > fresh.index("fetch")

    # Without the filter the stale ratio alone outranked the static head.
    unfiltered = tier_score.rank_tiers(LADDER, records, now=NOW, max_age_seconds=0.0)
    assert unfiltered[0] == "browser"


def test_stale_tier_keeps_its_rung_it_is_not_banned() -> None:
    """A stale record forfeits its promotion, but the ladder stays complete.

    Unlike a chronic failure (fresh evidence the method broke), staleness only
    proves we used to have evidence — so the rung must stay retryable rather
    than vanish from the ladder and strand the scrape.
    """
    ranked = tier_score.rank_tiers(LADDER, {"browser": _ancient()}, now=NOW)
    assert ranked == LADDER
    assert len(ranked) == len(LADDER)


def test_stale_is_a_hard_cut_not_a_score_penalty() -> None:
    """Past the bound the record is excluded, not merely out-scored."""
    assert tier_score.is_stale(_ancient(), NOW, 3600.0) is True
    assert tier_score.is_stale(_ancient(), NOW, 0.0) is False  # filter disabled


def test_fresh_record_at_the_boundary_is_kept() -> None:
    """Inside the window the tier is still promoted normally."""
    inside = FakeTier(successes=100, last_success_at=NOW - DOMAIN_MEMORY_MAX_AGE_SECONDS)
    assert tier_score.is_stale(inside, NOW, DOMAIN_MEMORY_MAX_AGE_SECONDS) is False
    ranked = tier_score.rank_tiers(LADDER, {"browser": inside}, now=NOW)
    assert ranked[0] == "browser"


def test_never_succeeded_record_is_not_stale() -> None:
    """No success means no positive evidence to expire — judged on failures."""
    never = FakeTier(successes=0, failures=1, last_failure_at=NOW - 10 * DAY)
    assert tier_score.is_stale(never, NOW, 3600.0) is False
    ranked = tier_score.rank_tiers(LADDER, {"browser": never}, now=NOW)
    assert "browser" in ranked


def test_every_candidate_stale_returns_static_ladder() -> None:
    """All evidence expired: the scraper must still get a full ladder."""
    records = {tier: _ancient() for tier in LADDER}
    assert tier_score.rank_tiers(LADDER, records, now=NOW) == LADDER


# ── The reader inherits it ───────────────────────────────────────────────────


def test_memory_reader_refuses_a_stale_tier() -> None:
    """``best_tier`` must not recommend a method that stopped working."""
    memory = DomainTierMemory()
    rec = memory.data["example.com"].setdefault("browser", TierRecord())
    rec.successes = 100
    rec.last_success_at = time.time() - 3 * DAY

    # Ladder: the stale tier falls back to its static position behind fetch.
    assert memory.reorder_for_domain("example.com", LADDER)[0] == "fetch"
    # Recommendation: the only proven tier is stale, so there is nothing to
    # recommend — None, not "browser". (It is not "fetch" either: an unseen
    # tier has no evidence, and recommending it is the caller's business.)
    assert memory.best_tier("example.com", LADDER) is None


def test_best_tier_refuses_a_stale_tier_even_when_it_is_the_only_candidate() -> None:
    """A caller who pinned one stale tier still gets no recommendation.

    The ladder-level filter alone would pass it through at its static
    position, so ``best_tier`` re-checks freshness on the record itself.
    """
    memory = DomainTierMemory()
    rec = memory.data["example.com"].setdefault("browser", TierRecord())
    rec.successes = 100
    rec.last_success_at = time.time() - 3 * DAY
    expected = ["browser"]
    assert memory.reorder_for_domain("example.com", ["browser"]) == expected
    assert memory.best_tier("example.com", ["browser"]) is None


def test_fresh_success_re_arms_the_tier() -> None:
    """Staleness is not a ban — a new success brings the tier straight back."""
    memory = DomainTierMemory()
    rec = memory.data["example.com"].setdefault("browser", TierRecord())
    rec.successes = 100
    rec.last_success_at = time.time() - 3 * DAY
    assert memory.best_tier("example.com", LADDER) is None

    memory.record("example.com", "browser", success=True, latency=10.0)
    assert memory.best_tier("example.com", LADDER) == "browser"
