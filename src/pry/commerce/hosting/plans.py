# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hosting plan catalog (server-authoritative pricing).

Mirrors the tier limits in :mod:`pry.commerce.billing.tiers`
(pro $49/mo, team $199/mo, enterprise custom quote).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pry.commerce.hosting.errors import PlanNotFound


@dataclass(frozen=True, slots=True)
class HostingPlan:
    """A hosted-instance plan with server-authoritative pricing.

    Mirrors the tier limits in :mod:`pry.commerce.billing.tiers`.
    """

    tier: str
    name: str
    price_usd_monthly: float | None
    max_concurrent_scrapes: int
    max_pages_month: int | None
    storage_gb: int
    features: list[str]

    @property
    def is_purchasable(self) -> bool:
        """True when the plan has a fixed monthly price (not a custom quote)."""
        return self.price_usd_monthly is not None


#: Canonical hosting plan catalog (matches billing.tiers pro/team/enterprise).
HOSTING_PLANS: dict[str, HostingPlan] = {
    "pro": HostingPlan(
        tier="pro",
        name="Pro",
        price_usd_monthly=49.0,
        max_concurrent_scrapes=100,
        max_pages_month=100_000,
        storage_gb=10,
        features=["priority_stealth", "residential_proxies", "standard_support"],
    ),
    "team": HostingPlan(
        tier="team",
        name="Team",
        price_usd_monthly=199.0,
        max_concurrent_scrapes=500,
        max_pages_month=500_000,
        storage_gb=50,
        features=[
            "priority_stealth",
            "residential_proxies",
            "batch",
            "custom_templates",
            "priority_support",
        ],
    ),
    "enterprise": HostingPlan(
        tier="enterprise",
        name="Enterprise",
        price_usd_monthly=None,  # custom quote
        max_concurrent_scrapes=1000,
        max_pages_month=None,  # unlimited
        storage_gb=500,
        features=["unlimited", "sla", "dedicated", "priority_support"],
    ),
}


def get_plan(tier: str) -> HostingPlan:
    """Resolve *tier* to a :class:`HostingPlan`. Raises :class:`PlanNotFound`."""
    if not tier:
        raise PlanNotFound("plan tier is required")
    plan = HOSTING_PLANS.get(tier.strip().lower())
    if plan is None:
        raise PlanNotFound(f"unknown hosting plan '{tier}'")
    return plan


def list_plans() -> list[dict[str, Any]]:
    """Return the hosting plan catalog (machine-readable)."""
    return [
        {
            "tier": p.tier,
            "name": p.name,
            "price_usd_monthly": p.price_usd_monthly,
            "max_concurrent_scrapes": p.max_concurrent_scrapes,
            "max_pages_month": p.max_pages_month,
            "storage_gb": p.storage_gb,
            "features": list(p.features),
            "purchasable": p.is_purchasable,
        }
        for p in HOSTING_PLANS.values()
    ]
