"""Cost- and latency-aware ranking for Pry's per-domain tier memory.

Pry keeps a :class:`~pry.engine.resilience.DomainTierMemory` that records, per
(remembered key, tier), how often a tier succeeded, how fast it was and what
it cost. This module is the single place that turns those raw counters into an
ordering — so the two readers (``best_tier`` and ``reorder_for_domain``)
can never disagree again.

Three properties this module is responsible for:

1. **Sample smoothing.** A tier with 1 success out of 1 attempt must not outrank
   a tier with 98 out of 100. Raw ratios do exactly that, which made a single
   lucky scrape permanently pin a domain to an expensive browser tier. We use
   an empirical-Bayes estimate with a prior, so a tier needs evidence before
   it displaces the static order.
2. **Cost awareness.** The vendors cannot do this: their per-page price hides
   the internal method cost, so a bot wall that forces JS rendering costs them
   the same credit as a clean fetch. Pry owns the ladder, so the marginal cost
   of the winning tier is a real term in the decision.
3. **One reader.** ``rank_tiers`` is the only ordering primitive. ``best_tier``
   is then simply "the head of the ranked list", which is what makes the two
   entry points agree by construction rather than by convention.

A blocked page is never recorded as a success by the caller
(``scraper_orchestrate._record_tier_outcome``), so success rate here means
"useful content came back", not "an HTTP 200 came back".
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# Empirical-Bayes prior: a tier is assumed to be mediocre until evidence says
# otherwise. With PRIOR_WEIGHT=4, a fresh 1/1 tier scores (1+2)/(1+4)=0.60 and a
# proven 98/100 tier scores (98+2)/(100+4)=0.962 — the lucky single sample can
# no longer outrank the proven one.
PRIOR_SUCCESS_RATE = 0.5
PRIOR_WEIGHT = 4.0

# Relative weights in the utility function. Success dominates; cost and
# latency break ties between tiers that are otherwise equally reliable.
COST_WEIGHT = 0.35
LATENCY_WEIGHT = 0.15

# A success inside this window earns the full recency bonus, decaying to
# zero at RECENCY_HALF_LIFE_SECONDS.
RECENCY_FULL_BONUS_SECONDS = 300.0
RECENCY_HALF_LIFE_SECONDS = 1800.0

# Latency is normalised against this budget; slower than this scores 0.
LATENCY_BUDGET_MS = 30_000.0

# A cost-normalising ceiling. Tiers are priced in USD per call; 0.05 is well
# above the most expensive rung of the 15-tier ladder.
COST_CEILING_USD = 0.05


class TierStats(Protocol):
    """The counters :func:`rank_tiers` needs from a stored record."""

    successes: int
    failures: int
    last_success_at: float
    last_failure_at: float
    total_latency: float
    cost_usd: float


def smoothed_success_rate(successes: int, failures: int) -> float:
    """Empirical-Bayes success rate; 0.5 (uninformative) with no samples."""
    return (successes + PRIOR_SUCCESS_RATE * PRIOR_WEIGHT) / (successes + failures + PRIOR_WEIGHT)


def recency_bonus(last_success_at: float, now: float) -> float:
    """Exponential decay in [0, 1] for how recently the tier last worked."""
    if last_success_at <= 0:
        return 0.0
    age = max(0.0, now - last_success_at)
    if age <= RECENCY_FULL_BONUS_SECONDS:
        return 1.0
    decay = (age - RECENCY_FULL_BONUS_SECONDS) / RECENCY_HALF_LIFE_SECONDS
    return max(0.0, 0.5**decay)


def latency_penalty(total_latency: float, successes: int) -> float:
    """Normalised 0..1 penalty; 0 when the tier is fast (or never ran)."""
    if successes <= 0 or total_latency <= 0:
        return 0.0
    mean_ms = total_latency / successes
    return min(1.0, mean_ms / LATENCY_BUDGET_MS)


def cost_penalty(cost_usd: float) -> float:
    """Normalised 0..1 penalty; 0 for a free tier."""
    if cost_usd <= 0:
        return 0.0
    return min(1.0, cost_usd / COST_CEILING_USD)


def utility(record: TierStats, now: float) -> float:
    """Ranking score for one tier. Higher is better.

    success (smoothed, dominant) + recency bonus - latency penalty - cost
    penalty. Cost and latency are bounded to [0, 1] so neither can outvote
    the success term on its own.
    """
    success = smoothed_success_rate(record.successes, record.failures)
    recency = recency_bonus(record.last_success_at, now)
    latency = latency_penalty(record.total_latency, record.successes)
    cost = cost_penalty(record.cost_usd)
    return success + 0.5 * recency - LATENCY_WEIGHT * latency - COST_WEIGHT * cost


def rank_tiers(
    candidates: Sequence[str],
    records: Mapping[str, TierStats],
    *,
    now: float | None = None,
    skip_min_samples: int = 3,
    skip_rate: float = 0.30,
    cooldown_seconds: float = 300.0,
) -> list[str]:
    """Order ``candidates`` by learned utility for one remembered key.

    This is the single ranking primitive in Pry. Behaviour:

    - Tiers with no history keep their static position (unseen tiers are
      never promoted and never demoted).
    - Chronic failures — at least ``skip_min_samples`` samples below
      ``skip_rate`` raw success — are dropped, so a domain stops paying for
      a method that does not work on it.
    - Tiers that failed within ``cooldown_seconds`` are kept but pushed to
      the back: a temporary demotion, not a ban.
    - Everything else is ordered by :func:`utility`, with the static index as
      the stable tie-break so equal scores keep the ladder's intent.

    Never returns an empty list: if every candidate would be dropped the
    static order is returned, because the scraper must always have a next
    rung to try.
    """
    order = list(candidates)
    if not records:
        return order
    at = time.time() if now is None else now
    static_index = {tier: i for i, tier in enumerate(order)}

    ranked: list[tuple[str, float, int]] = []
    cooled: list[tuple[str, int]] = []
    for tier in order:
        record = records.get(tier)
        if record is None:
            ranked.append((tier, 0.0, static_index[tier]))
            continue
        samples = record.successes + record.failures
        if samples >= skip_min_samples and record.successes / samples < skip_rate:
            continue
        if record.last_failure_at > 0 and at - record.last_failure_at < cooldown_seconds:
            cooled.append((tier, static_index[tier]))
            continue
        ranked.append((tier, utility(record, at), static_index[tier]))

    ranked.sort(key=lambda item: (-item[1], item[2]))
    cooled.sort(key=lambda item: item[1])
    return [tier for tier, _, _ in ranked] + [tier for tier, _ in cooled] or order


__all__ = [
    "COST_WEIGHT",
    "LATENCY_WEIGHT",
    "PRIOR_WEIGHT",
    "cost_penalty",
    "latency_penalty",
    "rank_tiers",
    "recency_bonus",
    "smoothed_success_rate",
    "utility",
]
