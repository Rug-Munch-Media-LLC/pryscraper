"""Pry - Apify Actor Factory: PPE economics.

Implements the profit model from Apify's monetization docs:

    profit = (0.8 * revenue) - platform costs

Platform costs are driven by memory (GB) x run time. The calculator turns
an actor's pricing events and expected workload into revenue/cost/profit
projections and a break-even event price, so presets are priced from
arithmetic instead of vibes.

Cost-per-CU is a configurable constant (Apify's published pay-per-use rate
at time of writing); verify against https://apify.com/pricing before
finalizing store prices.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from dataclasses import dataclass

# Apify compute unit: 1 GB of RAM for 1 hour. Published PPE-relevant rate.
COST_PER_CU_USD = 0.4
REVENUE_SHARE = 0.8  # developer keeps 80% of charged revenue


@dataclass(frozen=True)
class WorkloadProfile:
    """Expected shape of one actor run."""

    items_per_run: int  # number of primary-event items produced
    seconds_per_item: float  # average processing time per item
    memory_mbytes: int  # allocated RAM


def platform_cost_usd(profile: WorkloadProfile) -> float:
    """Estimated compute cost of one run: GB-hours x rate."""
    gb = profile.memory_mbytes / 1024
    total_hours = (profile.seconds_per_item * profile.items_per_run) / 3600
    return round(gb * total_hours * COST_PER_CU_USD, 6)


def run_economics(
    *,
    price_per_item_usd: float,
    profile: WorkloadProfile,
    include_synthetic_start: bool = True,
) -> dict[str, float]:
    """Revenue / cost / profit projection for one run.

    Includes the synthetic apify-actor-start event at its recommended
    default price ($0.00005 per GB-start) when enabled - docs recommend
    keeping it enabled on all PPE actors.
    """
    revenue = price_per_item_usd * profile.items_per_run
    if include_synthetic_start:
        gb = max(1, profile.memory_mbytes // 1024) or 1
        # docs: charged once up to 1GB, once per extra GB above it
        starts = max(1, (profile.memory_mbytes + 1023) // 1024)
        revenue += 0.00005 * starts * gb if gb > 1 else 0.00005
    costs = platform_cost_usd(profile)
    profit = REVENUE_SHARE * revenue - costs
    return {
        "revenue_usd": round(revenue, 6),
        "platform_cost_usd": round(costs, 6),
        "profit_usd": round(profit, 6),
        "margin": round(profit / revenue, 4) if revenue > 0 else 0.0,
    }


def break_even_price_usd(profile: WorkloadProfile, *, target_margin: float = 0.5) -> float:
    """Minimum per-item price so margin >= target_margin.

    Solves: (0.8*price*n - cost) / (price*n) >= target_margin
        =>  price >= cost / (n * (REVENUE_SHARE - target_margin))
    """
    cost = platform_cost_usd(profile)
    n = max(1, profile.items_per_run)
    denom = n * (REVENUE_SHARE - target_margin)
    if denom <= 0:
        raise ValueError("target_margin must be below the revenue share")
    return round(cost / denom, 6)


def monthly_projection(
    *,
    price_per_item_usd: float,
    profile: WorkloadProfile,
    runs_per_day: int,
) -> dict[str, float]:
    """30-day projection at a steady run cadence."""
    one = run_economics(price_per_item_usd=price_per_item_usd, profile=profile)
    scale = runs_per_day * 30
    return {
        "runs": scale,
        "revenue_usd": round(one["revenue_usd"] * scale, 2),
        "platform_cost_usd": round(one["platform_cost_usd"] * scale, 2),
        "profit_usd": round(one["profit_usd"] * scale, 2),
    }
