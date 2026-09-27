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

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pry.engine import tier_score

if TYPE_CHECKING:
    from pry.engine.method_stats_store import MethodStatsStore

logger = logging.getLogger(__name__)

# Adaptive fallback ordering.
# A tier is skipped for a domain once it has this many samples and a success
# rate below this threshold (chronic failure) — don't waste requests on it.
DOMAIN_FAILURE_SKIP_MIN_SAMPLES = 3
DOMAIN_FAILURE_SKIP_RATE = 0.30
# A tier that just failed is demoted to the back of the chain for this long.
DOMAIN_TIER_COOLDOWN_SECONDS = 300.0
# A tier whose last success is older than this is not ranked on its history at
# all (see tier_score.is_stale). Re-declared rather than imported from
# ``resilience`` because that module imports this one; ``resilience`` re-exports
# it as DOMAIN_MEMORY_MAX_AGE_SECONDS so the documented name still resolves.
DOMAIN_MEMORY_MAX_AGE_SECONDS = 3600.0

__all__ = [
    "DOMAIN_FAILURE_SKIP_MIN_SAMPLES",
    "DOMAIN_FAILURE_SKIP_RATE",
    "DOMAIN_MEMORY_MAX_AGE_SECONDS",
    "DOMAIN_TIER_COOLDOWN_SECONDS",
    "DomainTierMemory",
    "TierRecord",
    "]",
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
    """Remember which tiers work best per domain.

    Hot cache first, durable store second. ``store`` buffers every outcome
    and flushes on a background thread, so ``record`` never blocks and a
    database outage costs durability only. ``store is None`` — the default —
    is today's behaviour exactly. ``tier_memory_db`` seeds the cache back.
    """

    data: dict[str, dict[str, TierRecord]] = field(default_factory=lambda: defaultdict(dict))
    store: MethodStatsStore | None = None

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

        A blocked attempt must be recorded with ``success=False`` — callers
        enforce that. The durable mirror is fire-and-forget: it buffers,
        returns and swallows DB errors, so this never blocks a scrape.
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
        if self.store is not None:
            self.store.record(
                domain,
                tier,
                win=success,
                latency_ms=latency * 1000.0,
                cost_usd=cost_usd,
                block_kind=block_kind,
            )

    def best_tier(self, domain: str, candidates: list[str]) -> str | None:
        """The tier a scrape should try first, or ``None`` if unproven.

        Derived from :func:`tier_score.rank_tiers`, the same primitive
        :meth:`reorder_for_domain` uses, so the two agree by construction. One
        deliberate difference: a cooling-down tier is *demoted* in the ladder
        but never *recommended* here. A stale tier is skipped here too, and
        independent of :meth:`reorder_for_domain`: "what should I try?" must
        never be answered from expired evidence even if a caller narrowed
        ``candidates`` down to a single stale tier, which the ladder-level
        filter alone would happily pass through at its static position.
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
            if tier_score.is_stale(rec, now, DOMAIN_MEMORY_MAX_AGE_SECONDS):
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
        max_age_seconds: float = DOMAIN_MEMORY_MAX_AGE_SECONDS,
    ) -> list[str]:
        """Return ``candidates`` reordered for ``domain`` using its history.

        The static order is the baseline. On top of it: proven tiers are
        promoted; tiers whose last success predates ``max_age_seconds`` are
        excluded so stale evidence decays out instead of pinning a domain;
        recently-failed tiers are demoted (cooldown, not a ban); chronic
        failures are skipped; unrecorded tiers keep their static position.
        Never empty — the scraper always has something to try.
        """
        return tier_score.rank_tiers(
            candidates,
            self.data.get(domain, {}),
            skip_min_samples=DOMAIN_FAILURE_SKIP_MIN_SAMPLES,
            skip_rate=DOMAIN_FAILURE_SKIP_RATE,
            cooldown_seconds=cooldown_seconds,
            max_age_seconds=max_age_seconds,
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
