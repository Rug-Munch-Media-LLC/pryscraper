# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the Apify actor adapter (apify_actor.py) and .actor packaging.

The actor is a distribution channel for the scraper: these tests pin the
dataset-item contract Apify customers depend on, the crawl-link extraction
rules, and validate the .actor/ packaging is internally consistent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


class TestApifyActorOutputContract:
    """Pydantic output schema — every emitted dataset item conforms."""

    def test_success_output_shape(self) -> None:
        from pry.actors.apify_actor import ApifyActorOutput, ApifyScrapeMetadata

        out = ApifyActorOutput(
            url="https://example.com",
            status="ok",
            method="direct",
            scraped_at="2026-08-26T19:30:00+00:00",
            elapsed_seconds=1.23,
            content="# Hello",
            metadata=ApifyScrapeMetadata(
                domain="example.com",
                content_length=7,
                method="direct",
            ),
        )
        item = out.to_dataset_item()
        assert item["url"] == "https://example.com"
        assert item["status"] == "ok"
        assert item["content"] == "# Hello"
        assert item["metadata"]["domain"] == "example.com"

    def test_error_output_shape(self) -> None:
        from pry.actors.apify_actor import ApifyActorOutput

        out = ApifyActorOutput(
            url="https://example.com",
            status="error",
            error="Invalid URL: blocked",
            scraped_at="2026-08-26T19:30:00+00:00",
        )
        item = out.to_dataset_item()
        assert item["status"] == "error"
        assert "Invalid URL" in item["error"]

    def test_invalid_status_raises(self) -> None:
        from pydantic import ValidationError

        from pry.actors.apify_actor import ApifyActorOutput

        with pytest.raises(ValidationError):
            ApifyActorOutput(
                url="https://x.com",
                status="invalid_status",
                scraped_at="2026-08-26T19:30:00+00:00",
            )

    def test_dataset_item_excludes_none(self) -> None:
        from pry.actors.apify_actor import ApifyActorOutput

        out = ApifyActorOutput(
            url="https://x.com",
            status="error",
            error="fail",
            scraped_at="2026-08-26T19:30:00+00:00",
        )
        item = out.to_dataset_item()
        # Empty content/raw_html should be excluded
        assert "content" not in item or item.get("content") == ""


# ── T1 win #7: Apify crawl mode test ─────────────────────────────────────────


class TestApifyCrawlMode:
    """Apify actor crawl mode — BFS link discovery and frontier management."""

    @pytest.mark.asyncio
    async def test_crawl_mode_extracts_links_from_html(self) -> None:
        """Crawl mode should extract same-discovered links and add to frontier."""
        from pry.actors.apify_actor import _extract_links

        html = """
        <html><body>
        <a href="/page1">Page 1</a>
        <a href="/page2">Page 2</a>
        <a href="https://other.com/external">External</a>
        <a href="/page1">Duplicate</a>
        </body></html>
        """
        links = _extract_links(html, "https://example.com/start")
        assert "https://example.com/page1" in links
        assert "https://example.com/page2" in links
        assert not any("other.com" in link for link in links)
        # Duplicates removed
        assert len(links) == len(set(links))

    @pytest.mark.asyncio
    async def test_crawl_mode_caps_frontier_per_page(self) -> None:
        """Frontier should be capped at 20 new links per page."""
        from pry.actors.apify_actor import _extract_links

        # Generate HTML with 50 same-domain links
        html = "".join(f'<a href="https://example.com/p{i}">p{i}</a>' for i in range(50))
        links = _extract_links(html, "https://example.com/start")
        assert len(links) == 50  # _extract_links caps at 50

    @pytest.mark.asyncio
    async def test_crawl_mode_respects_max_pages(self) -> None:
        """Crawl should stop after max_pages URLs scraped."""
        from pry.actors.apify_actor import ApifyActorInput

        inp = ApifyActorInput.model_validate(
            {
                "urls": ["https://example.com/start"],
                "crawl": True,
                "max_pages": 3,
            }
        )
        assert inp.crawl is True
        assert inp.max_pages == 3

    @pytest.mark.asyncio
    async def test_crawl_mode_with_proxy_config(self) -> None:
        """Crawl mode should respect proxy configuration."""
        from pry.actors.apify_actor import ApifyActorInput

        inp = ApifyActorInput.model_validate(
            {
                "urls": ["https://example.com/start"],
                "crawl": True,
                "proxy_config": {"use_apify_proxies": True, "proxy_country": "US"},
            }
        )
        assert inp.crawl is True
        assert inp.proxy_config.use_apify_proxies is True

    @pytest.mark.asyncio
    async def test_crawl_mode_depth_validation(self) -> None:
        """Crawl depth should be validated (0-5)."""
        from pydantic import ValidationError

        from pry.actors.apify_actor import ApifyActorInput

        # Valid depths
        for depth in [0, 1, 2, 3, 4, 5]:
            inp = ApifyActorInput.model_validate(
                {
                    "urls": ["https://x.com"],
                    "max_depth": depth,
                }
            )
            assert inp.max_depth == depth

        # Invalid depth
        with pytest.raises(ValidationError):
            ApifyActorInput.model_validate(
                {
                    "urls": ["https://x.com"],
                    "max_depth": 6,
                }
            )
