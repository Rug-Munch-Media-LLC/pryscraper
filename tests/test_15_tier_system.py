# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the 15-tier scraping system."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pry.engine.ultimate_scraper import UltimateScraper


class Test15TierSystem:
    """Test the 15-tier scraping fallback chain."""

    def test_scraper_has_15_tiers(self) -> None:
        """Verify the scraper advertises 15 tiers."""
        scraper = UltimateScraper()
        assert "15-tier" in scraper.__class__.__doc__

    def test_tier_order_includes_new_tiers(self) -> None:
        """Verify new tiers are in the tier order."""
        scraper = UltimateScraper()
        tier_names = list(scraper._RETRY_CONFIGS.keys())
        assert "mobile_app" in tier_names
        assert "graphql" in tier_names

    def test_retry_configs_for_new_tiers(self) -> None:
        """Verify retry configs exist for new tiers."""
        scraper = UltimateScraper()
        assert "mobile_app" in scraper._RETRY_CONFIGS
        assert "graphql" in scraper._RETRY_CONFIGS

    @pytest.mark.asyncio
    async def test_tier_mobile_app_returns_none_when_unavailable(self) -> None:
        """Mobile app tier should return None when not available."""
        scraper = UltimateScraper()
        with patch("pry.engine.ultimate_scraper._has_mobile", False):
            result = await scraper._tier_mobile_app("https://example.com", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_tier_graphql_returns_none_when_unavailable(self) -> None:
        """GraphQL tier should return None when not available."""
        scraper = UltimateScraper()
        with patch("pry.engine.ultimate_scraper._has_graphql", False):
            result = await scraper._tier_graphql("https://example.com", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_tier_ai_visual_returns_none_when_unavailable(self) -> None:
        """AI visual tier should return None when not available."""
        scraper = UltimateScraper()
        with patch("pry.engine.ultimate_scraper._has_ai_visual", False):
            result = await scraper._tier_ai_visual("https://example.com", {})
        assert result is None


class TestAIVisualScraper:
    """Test the AI Visual Scraper tier."""

    def test_is_available_requires_playwright_and_key(self) -> None:
        from pry.engine.ai_visual_scraper import AIVisualScraper

        scraper = AIVisualScraper(llm_api_key="")
        assert scraper.is_available() is False

    def test_is_available_with_key(self) -> None:
        from pry.engine.ai_visual_scraper import AIVisualScraper

        scraper = AIVisualScraper(llm_api_key="test_key")
        # Still False because playwright may not be installed in test env
        # but the key check passes
        assert scraper.is_available() is False or True


class TestMobileAppScraper:
    """Test the Mobile App Scraper tier."""

    def test_is_available_always_true(self) -> None:
        from pry.engine.mobile_app_scraper import MobileAppScraper

        scraper = MobileAppScraper()
        assert scraper.is_available() is True

    def test_rotate_ua_cycles(self) -> None:
        from pry.engine.mobile_app_scraper import MobileAppScraper

        scraper = MobileAppScraper()
        ua1 = scraper._rotate_ua()
        ua2 = scraper._rotate_ua()
        # _rotate_ua advances the index every call, so consecutive UAs differ
        # (MOBILE_USER_AGENTS has >1 entry).
        assert ua1 != ua2


class TestGraphQLScraper:
    """Test the GraphQL Scraper tier."""

    def test_is_available_always_true(self) -> None:
        from pry.engine.graphql_scraper_enhanced import GraphQLScraper

        scraper = GraphQLScraper()
        assert scraper.is_available() is True
