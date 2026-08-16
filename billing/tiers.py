"""Pry — subscription tier definitions for billing enforcement.

Tiers are a plain-data contract consumed by :mod:`billing.enforcer`.
No external dependencies and no app wiring: importing this module must be
safe from any context (CLI, middleware, tests).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True, slots=True)
class Tier:
    """A subscription tier with its pricing and enforcement limits.

    Attributes:
        name: Canonical lowercase tier name (``free``, ``pro``, ``team``,
            ``enterprise``).
        price_usd_monthly: Monthly list price in USD. ``None`` means the
            tier is not sold at a fixed monthly price (FREE or custom
            ENTERPRISE).
        request_quota_monthly: Max requests per calendar month. ``None``
            means no monthly cap (FREE / ENTERPRISE).
        concurrent_limit: Max in-flight requests allowed for the tier.
        feature_flags: Capability set (stealth level, batch, templates...).
        rate_limit_rpm: Max requests per minute. ``None`` means no cap.
    """

    name: str
    price_usd_monthly: float | None
    request_quota_monthly: int | None
    concurrent_limit: int
    feature_flags: set[str] = field(default_factory=set)
    rate_limit_rpm: int | None = None

    @property
    def is_unlimited(self) -> bool:
        """True when the tier has no monthly request cap."""
        return self.request_quota_monthly is None


#: Canonical tier table. Keep names lowercase; ``TIERS["free"]`` is the
#: fallback for unknown/missing API keys.
TIERS: Final[dict[str, Tier]] = {
    "free": Tier(
        name="free",
        price_usd_monthly=None,
        request_quota_monthly=None,  # pay-per-call (x402), no monthly cap
        concurrent_limit=1,
        feature_flags={"x402_pay_per_call", "basic_stealth"},
        rate_limit_rpm=30,  # safety valve so a single key can't hammer infra
    ),
    "pro": Tier(
        name="pro",
        price_usd_monthly=49.0,
        request_quota_monthly=50_000,
        concurrent_limit=5,
        feature_flags={
            "x402_pay_per_call",
            "priority_stealth",
            "residential_proxies",
            "standard_support",
        },
        rate_limit_rpm=120,
    ),
    "team": Tier(
        name="team",
        price_usd_monthly=199.0,
        request_quota_monthly=500_000,
        concurrent_limit=20,
        feature_flags={
            "x402_pay_per_call",
            "priority_stealth",
            "residential_proxies",
            "standard_support",
            "batch",
            "custom_templates",
            "priority_support",
        },
        rate_limit_rpm=600,
    ),
    "enterprise": Tier(
        name="enterprise",
        price_usd_monthly=None,  # custom quote
        request_quota_monthly=None,  # unlimited
        concurrent_limit=100,
        feature_flags={
            "x402_pay_per_call",
            "priority_stealth",
            "residential_proxies",
            "standard_support",
            "batch",
            "custom_templates",
            "priority_support",
            "unlimited",
            "sla",
            "dedicated",
        },
        rate_limit_rpm=None,  # no rpm cap under SLA
    ),
}

#: Tier used when no API key is supplied or the key is unknown.
DEFAULT_TIER: Final[Tier] = TIERS["free"]

#: Ordered canonical tier names (free < pro < team < enterprise).
TIER_NAMES: Final[tuple[str, ...]] = tuple(TIERS)


def get_tier(name: str | None) -> Tier:
    """Return the tier for *name*, defaulting to FREE for unknown names.

    Lookups are case-insensitive and whitespace-tolerant. ``None`` (no
    key supplied) always resolves to FREE.
    """
    if name is None:
        return DEFAULT_TIER
    return TIERS.get(name.strip().lower(), DEFAULT_TIER)
