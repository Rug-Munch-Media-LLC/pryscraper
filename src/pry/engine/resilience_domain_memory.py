"""Per-domain tier memory for the adaptive fallback chain.

Extracted from ``pry.engine.resilience`` so the learned "which tier works on
this domain" intelligence lives in one place. ``resilience.py`` keeps
re-exporting :class:`TierRecord` and :class:`DomainTierMemory`, so every
existing caller and test import is unchanged.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pry.engine import tier_score

# Adaptive fallback ordering.
# A tier is skipped for a domain once it has this many samples and a success
# rate below this threshold (chronic failure) — don't waste requests on it.
DOMAIN_FAILURE_SKIP_MIN_SAMPLES = 3
DOMAIN_FAILURE_SKIP_RATE = 0.30
# A tier that just failed is demoted to the back of the chain for this long.
DOMAIN_TIER_COOLDOWN_SECONDS = 300.0

__all__ = [
    "DOMAIN_FAILURE_SKIP_MIN_SAMPLES",
    "DOMAIN_FAILURE_SKIP_RATE",
    "DOMAIN_TIER_COOLDOWN_SECONDS",
    "DomainTierMemory",
    "TierRecord",
]


@dataclass
class TierRecord:
    successes: int = 0
    failures: int = 0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    total_latency: float = 0.0
    # Accumulated cost in USD across every recorded attempt for this tier.
    # Pry owns the whole ladder, so the marginal cost of a tier is a real
    # input to the ranking (see engine/tier_score.cost_penalty) — the
    # per-page x402 price cannot express it.
    cost_usd: float = 0.0
    # Last BlockSignal.kind seen for this tier (cloudflare, captcha,
    # js_required, rate_limited, access_denied). Kept for diagnostics and
    # future affinity rules; never treated as success.
    last_block_kind: str = ""

    @property
    def score(self) -> float:
        """Learned utility. Higher = more preferred.

        Delegates to :func:`pry.engine.tier_score.utility` so this property,
        ``best_tier`` and ``reorder_for_domain`` can never rank differently.
        """
        return tier_score.utility(self, time.time())


@dataclass
class DomainTierMemory:
    """Remember which tiers work best per domain."""

    data: dict[str, dict[str, TierRecord]] = field(default_factory=lambda: defaultdict(dict))

    def record(
        self,
        domain: str,
        tier: str,
        success: bool,
        latency: float = 0.0,
        *,
        cost_usd: float = 0.0,
        block_kind: str = "",
    ) -> None:
        """Record one tier outcome for ``domain``.

        ``cost_usd`` and ``block_kind`` are optional so existing call sites
        keep working; both feed the cost-aware ranking in
        :mod:`pry.engine.tier_score`. A blocked attempt must be recorded
        with ``success=False`` — callers already enforce that.
        """
        rec = self.data[domain].setdefault(tier, TierRecord())
        if success:
            rec.successes += 1
            rec.last_success_at = time.time()
        else:
            rec.failures += 1
            rec.last_failure_at = time.time()
            if block_kind:
                rec.last_block_kind = block_kind
        rec.total_latency += latency
        rec.cost_usd += cost_usd

    def best_tier(self, domain: str, candidates: list[str]) -> str | None:
        """The tier a scrape should try first, or ``None`` if unproven.

        Derived from :func:`tier_score.rank_tiers` — the same primitive
        :meth:`reorder_for_domain` uses — so the two readers agree by
        construction instead of by convention.

        One deliberate difference: a tier that failed inside the cooldown
        window is *demoted* by ``reorder_for_domain`` (still reachable at the
        back of the ladder) but is never *recommended* here. A caller asking
        "what should I try?" must not be handed something that just failed,
        so the cooled tail is skipped. ``None`` means nothing in
        ``candidates`` is both proven and not cooling down.
        """
        records = self.data.get(domain, {})
        if not records:
            return None
        now = time.time()
        cooldown = DOMAIN_TIER_COOLDOWN_SECONDS
        for tier in self.reorder_for_domain(domain, candidates):
            rec = records.get(tier)
            if rec is None or rec.successes == 0:
                continue
            if rec.last_failure_at > 0 and now - rec.last_failure_at < cooldown:
                continue
            return tier
        return None

    def reorder_for_domain(
        self,
        domain: str,
        candidates: list[str],
        *,
        cooldown_seconds: float = DOMAIN_TIER_COOLDOWN_SECONDS,
    ) -> list[str]:
        """Return ``candidates`` reordered for ``domain`` using its history.

        The static fallback order is the baseline. On top of it:

        - Proven tiers (highest score) are promoted to the front, so the
          domain's best-known method is tried first.
        - Tiers with a recent failure (within ``cooldown_seconds``) are
          demoted to the back — a temporary cooldown, not a ban.
        - Tiers with >= ``DOMAIN_FAILURE_SKIP_MIN_SAMPLES`` samples and a
          success rate below ``DOMAIN_FAILURE_SKIP_RATE`` are skipped for
          this domain entirely (chronic failure).
        - Tiers with no history keep their static position.

        Never returns an empty list: if every candidate would be skipped the
        static order is returned so the scraper always has something to try.
        """
        return tier_score.rank_tiers(
            candidates,
            self.data.get(domain, {}),
            skip_min_samples=DOMAIN_FAILURE_SKIP_MIN_SAMPLES,
            skip_rate=DOMAIN_FAILURE_SKIP_RATE,
            cooldown_seconds=cooldown_seconds,
        )

    def to_dict(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {
            domain: {
                tier: {
                    "successes": rec.successes,
                    "failures": rec.failures,
                    "last_success_at": rec.last_success_at,
                    "last_failure_at": rec.last_failure_at,
                    "total_latency": rec.total_latency,
                    "cost_usd": rec.cost_usd,
                    "last_block_kind": rec.last_block_kind,
                    "score": round(rec.score, 3),
                }
                for tier, rec in tiers.items()
            }
            for domain, tiers in self.data.items()
        }
