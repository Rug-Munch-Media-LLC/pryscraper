"""Pry — Referral / Affiliate revenue system (facade).

Thin re-export facade over the ``referrals`` package. Kept for backward
compatibility: existing ``from referrals import X`` imports keep working.

Implementation lives in:
  - ``referrals.catalog`` — static affiliate program/referral data
  - ``referrals.routes`` — link generation + click tracking + conversion helpers
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from referrals.catalog import PROVIDER_CATALOG
from referrals.routes import ReferralTracker

__all__ = ["PROVIDER_CATALOG", "ReferralTracker"]
