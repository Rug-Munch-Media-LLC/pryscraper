# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Delegated-scraper tiers (AI visual, mobile app, GraphQL).

Extracted from ``tiers_special`` during the size-ratchet split.
:class:`TierDelegatedMixin` is the BASE of :class:`~pry.engine.tiers_special.
TierSpecialMixin`, so every method here resolves through the existing mixin
chain and ``self._tier_*`` still yields the identical function object. The
ladder in :mod:`pry.engine.tier_chain` binds those bound methods positionally;
the signatures below are unchanged, parameter for parameter.
"""

from __future__ import annotations

import logging
from typing import Any

from pry.engine.tiers_base import _us_flag

logger = logging.getLogger(__name__)


class TierDelegatedMixin:
    """Tiers that delegate the fetch to an optional external scraper."""

    async def _tier_ai_visual(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 13: AI Visual Scraper — screenshot + LLM vision extraction."""
        if not _us_flag("_has_ai_visual") or not _us_flag("_ai_visual"):
            return None
        try:
            return await _us_flag("_ai_visual").scrape(url, opts)
        except Exception as e:
            logger.debug("ai_visual_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_mobile_app(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 14: Mobile App API — impersonate mobile clients."""
        if not _us_flag("_has_mobile") or not _us_flag("_mobile_scraper"):
            return None
        try:
            return await _us_flag("_mobile_scraper").scrape(url, opts)
        except Exception as e:
            logger.debug("mobile_app_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_graphql(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 15: GraphQL API Discovery — find and query GraphQL endpoints."""
        if not _us_flag("_has_graphql") or not _us_flag("_graphql_scraper"):
            return None
        try:
            return await _us_flag("_graphql_scraper").scrape(url, opts)
        except Exception as e:
            logger.debug("graphql_failed", extra={"error": str(e)[:200]})
        return None
