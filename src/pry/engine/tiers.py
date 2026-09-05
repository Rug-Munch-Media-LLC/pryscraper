"""Tier implementations for the UltimateScraper fallback chain (facade).

The concrete ``_tier_*`` fetch strategies and shared helpers live in focused
modules:

- :mod:`pry.engine.tiers_base` — shared helpers (headers, validation, text
  extraction, block-signal detection, fallback telemetry)
- :mod:`pry.engine.tiers_http` — simple HTTP tiers (direct, premium proxy,
  cloudscraper, flaresolverr)
- :mod:`pry.engine.tiers_browser` — browser tiers (undetected, playwright,
  TLS fingerprint, camoufox)
- :mod:`pry.engine.tiers_special` — special tiers (googlebot, archive,
  google cache, tor, ai visual, mobile app, graphql)

``UltimateScraper`` composes these via ``TierMixin``; the fallback-chain
orchestration stays in ``ultimate_scraper.py``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry.engine.tiers_base import TierBase
from pry.engine.tiers_browser import TierBrowserMixin
from pry.engine.tiers_http import TierHTTPMixin
from pry.engine.tiers_special import TierSpecialMixin

__all__ = ["TierMixin"]


class TierMixin(TierBase, TierHTTPMixin, TierBrowserMixin, TierSpecialMixin):
    """Concrete scraping tiers, mixed into :class:`UltimateScraper`."""
