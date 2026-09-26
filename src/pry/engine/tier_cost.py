"""Per-tier cost model for Pry's learned method ranking.

Pry owns the whole 15-tier ladder, so unlike every hosted vendor we know what
a given tier actually costs to run. That is the input
:mod:`pry.engine.tier_score` needs to trade "this method always works" against
"this method works but costs 40x more", and it is the one dimension a
per-page x402 price cannot express for a customer.

Two cost classes:

- **Flat tiers** cost nothing per attempt: a plain HTTP fetch, an archived
  copy, Google's cache, a local FlareSolverr/Camoufox process already
  resident. Their only cost is the latency they burn, which the ranking
  already prices separately, so their unit cost is 0.0.
- **Paid egress** (a premium proxy) costs per request and is unknown until
  the proxy operator's price is configured, so it degrades to 0.0 rather
  than inventing a number. Set ``PRY_PREMIUM_PROXY_COST_USD`` to make the
  expensive rung visible to the ranking; leaving it unset means the paid tier
  is ranked purely on success, which is the pre-cost behaviour.

Nothing here invents a price. Every value is either structurally free, or
read from operator configuration, or explicitly unknown.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import os

# Tiers whose marginal cost is structural zero: the work happens in a process
# we already run, or is a free upstream (archive.org, Google cache). Their
# latency is priced separately by tier_score.latency_penalty.
FREE_TIERS: frozenset[str] = frozenset(
    {
        "direct",
        "tls_fingerprint",
        "cloudscraper",
        "tor",
        "archive",
        "google_cache",
        "flaresolverr",
        "undetected",
        "camoufox",
        "playwright",
        "googlebot",
    }
)

# The only tier whose cost is a real outbound purchase.
PAID_TIERS: frozenset[str] = frozenset({"premium_proxy"})

PREMIUM_COST_ENV = "PRY_PREMIUM_PROXY_COST_USD"


def premium_proxy_cost_usd() -> float:
    """USD per premium-proxy request, or 0.0 when unconfigured.

    Read per call rather than at import so a test (or an operator rotating
    the price) does not need to reload the module. A malformed or negative
    value is treated as unknown, never as free.
    """
    raw = os.environ.get(PREMIUM_COST_ENV, "").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return value if value > 0 else 0.0


def tier_cost(tier_name: str) -> float:
    """Marginal cost in USD of one attempt of ``tier_name``.

    Args:
        tier_name: A rung from Pry's tier ladder, e.g. ``"playwright"``.

    Returns:
        0.0 for structurally free tiers and for paid tiers whose price the
        operator has not configured. This is deliberate: an unknown cost
        must not silently become "free", but it also must not be invented,
        so the caller can distinguish via :func:`premium_proxy_cost_usd`.
    """
    if tier_name in FREE_TIERS:
        return 0.0
    if tier_name in PAID_TIERS:
        return premium_proxy_cost_usd()
    return 0.0


def is_cost_known(tier_name: str) -> bool:
    """Whether :func:`tier_cost` returns a real price rather than a default.

    Used by the diagnostics surface so an operator can see that the paid
    rung is currently ranked without a cost term instead of assuming the
    cost model is fully configured.
    """
    if tier_name in FREE_TIERS:
        return True
    if tier_name in PAID_TIERS:
        return premium_proxy_cost_usd() > 0
    return False


__all__ = [
    "FREE_TIERS",
    "PAID_TIERS",
    "PREMIUM_COST_ENV",
    "is_cost_known",
    "premium_proxy_cost_usd",
    "tier_cost",
]
