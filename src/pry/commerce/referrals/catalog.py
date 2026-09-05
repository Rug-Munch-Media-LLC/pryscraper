"""Pry — Referral / Affiliate program catalog (facade).

Static catalog of affiliate/referral programs across 60+ providers,
grouped by category. Data lives in the ``catalog_*`` modules; this
module merges them into the canonical ``PROVIDER_CATALOG`` mapping.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from pry.commerce.referrals.catalog_ai import CATEGORIES as _AI
from pry.commerce.referrals.catalog_infra import CATEGORIES as _INFRA
from pry.commerce.referrals.catalog_scraping import CATEGORIES as _SCRAPING

# Provider catalog with referral program details
# Format: { category: [ {name, url, commission, cookie_days, ...} ] }
PROVIDER_CATALOG: dict[str, list[dict]] = {**_AI, **_INFRA, **_SCRAPING}

__all__ = ["PROVIDER_CATALOG"]
