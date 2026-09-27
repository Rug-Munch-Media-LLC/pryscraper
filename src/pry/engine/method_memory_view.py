"""Read surface for Pry's learned method memory.

``pry.engine.resilience`` accumulates one :class:`TierRecord` per
(domain, tier) — successes, failures, latency, cost and the last block kind —
and ranks them with :mod:`pry.engine.tier_score`. That is the WRITE side, and
until now it was write-only: nothing could read it, so its usefulness could not
be verified and an agent could not answer "how should I fetch this domain?".

This module is the pure read side. It turns one domain's stored records into:

- the ranked tier order (via the same ``reorder_for_domain`` the scraper uses,
  so the answer cannot disagree with what the scraper will actually do),
- per-tier success rate, sample count, average latency, accumulated cost and
  ``last_block_kind``,
- a plain-language reason for the top pick.

Two rules the tests hold us to:

1. **No fabrication.** A domain with no history yields an empty tier list, a
   ``null`` top pick and a cold-start reason. Tiers are never invented, and a
   domain that has only failed still reports a pick (``best_tier`` returns
   ``None`` in that case — see the cooldown note in
   :meth:`DomainTierMemory.best_tier`).
2. **Honest numbers.** ``success_rate`` is the raw ratio (``0.0`` with no
   samples) because an operator auditing the memory must not see a prior
   smuggled in as data. The ranking's empirical-Bayes view of the same
   counters is reported separately as ``smoothed_success_rate``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from pry.engine import tier_score
from pry.engine.tier_cost import is_cost_known

if TYPE_CHECKING:
    from pry.engine.resilience import TierRecord

COLD_START_REASON = (
    "No scraped history for this domain yet, so no tier is proven. "
    "Fetches fall back to the static ladder order (cheapest, free tiers first)."
)


def _tier_entry(tier: str, record: TierRecord, rank: int) -> dict[str, Any]:
    """One ranked tier's observed counters plus its cost model terms."""
    successes = max(0, record.successes)
    failures = max(0, record.failures)
    samples = successes + failures
    return {
        "tier": tier,
        "rank": rank,
        "samples": samples,
        "successes": successes,
        "failures": failures,
        "success_rate": round(successes / samples, 4) if samples else 0.0,
        "smoothed_success_rate": round(tier_score.smoothed_success_rate(successes, failures), 4),
        # Denominator is SUCCESSES, matching tier_score.latency_penalty — the
        # stored counter is charged on every attempt, failures included, so a
        # per-attempt mean would misreport the number the ranking actually uses.
        "latency_per_success_ms": round(record.total_latency / successes, 2) if successes else 0.0,
        "cost_usd": round(record.cost_usd, 6),
        "cost_known": is_cost_known(tier),
        "last_block_kind": record.last_block_kind or None,
        "last_success_at": record.last_success_at or None,
        "last_failure_at": record.last_failure_at or None,
        "score": round(record.score, 3),
    }


def _reason(domain: str, top: dict[str, Any], cost_known: bool) -> str:
    """Plain-language justification for the top pick (one sentence + evidence)."""
    evidence = (
        f"Last block seen: {top['last_block_kind']}."
        if top["last_block_kind"]
        else "No recorded block on this tier."
    )
    cost = (
        f"Cost model: ${top['cost_usd']:.6f} accumulated over those samples."
        if cost_known
        else "Cost is unconfigured for this tier, so it was ranked on success alone."
    )
    return (
        f"Try {top['tier']} first for {domain}: it ranks first on {top['samples']} "
        f"samples at {top['success_rate'] * 100:.1f}% success, "
        f"{top['latency_per_success_ms']:.0f}ms average latency. {evidence} {cost}"
    )


def explain_top_pick(domain: str, ranked: list[dict[str, Any]]) -> str | None:
    """Reason string for ``ranked[0]``, or the cold-start message when empty."""
    if not ranked:
        return COLD_START_REASON
    return _reason(domain, ranked[0], cost_known=bool(ranked[0]["cost_known"]))


def domain_method_plan(domain: str, now: float | None = None) -> dict[str, Any]:
    """Ranked method memory for ``domain`` — the read surface of the ladder.

    Args:
        domain: Hostname exactly as the scraper keys it (e.g. ``example.com``).
        now: Optional clock override for deterministic tests.

    Returns:
        A payload with ``domain``, the ranked ``tiers`` (each carrying success
        rate, sample count, latency, cost and ``last_block_kind``), the ``top_pick``
        tier name, a plain-language ``reason`` and a ``cold_start`` flag. When the
        domain has no history, ``tiers`` is empty and ``top_pick`` is ``None`` —
        no tier is fabricated.
    """
    from pry.engine.resilience import registry

    domain = (domain or "").strip().lower()
    memory = registry.domain_memory
    if not domain:
        return {
            "domain": domain,
            "tiers": [],
            "top_pick": None,
            "reason": COLD_START_REASON,
            "cold_start": True,
            "generated_at": time.time() if now is None else now,
        }

    records = dict(memory.data.get(domain, {}))
    ranked: list[dict[str, Any]] = []
    if records:
        # Same primitive the scraper uses, so the plan is what will happen.
        order = tier_score.rank_tiers(list(records), records, now=now)
        ranked = [_tier_entry(tier, records[tier], idx + 1) for idx, tier in enumerate(order)]
    return {
        "domain": domain,
        "tiers": ranked,
        "top_pick": ranked[0]["tier"] if ranked else None,
        "reason": explain_top_pick(domain, ranked),
        "cold_start": not ranked,
        "generated_at": time.time() if now is None else now,
    }


__all__ = [
    "COLD_START_REASON",
    "domain_method_plan",
    "explain_top_pick",
]
