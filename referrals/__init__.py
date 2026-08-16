"""Pry — Referral / Affiliate revenue system.

Tracks clicks, conversions, and revenue across 60+ providers.
Supports x402 (HTTP 402) pay-per-scrape protocol for monetization.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from referrals.catalog import PROVIDER_CATALOG
from referrals.routes import ReferralTracker

__all__ = ["PROVIDER_CATALOG", "ReferralTracker"]
