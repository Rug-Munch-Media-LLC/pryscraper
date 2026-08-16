"""Pry — subscription billing: tier table + quota/rate-limit enforcement.

Self-contained module for the marketing site's monthly Pro/Team/Enterprise
tiers. Importing :mod:`billing` has no side effects and requires no app
wiring: the API middleware constructs a :class:`BillingEnforcer` and calls
:meth:`BillingEnforcer.check_request` per request.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from billing.enforcer import BillingEnforcer
from billing.tiers import DEFAULT_TIER, TIER_NAMES, TIERS, Tier, get_tier

__all__ = [
    "DEFAULT_TIER",
    "TIERS",
    "TIER_NAMES",
    "BillingEnforcer",
    "Tier",
    "get_tier",
]
