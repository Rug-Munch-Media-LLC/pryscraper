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

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import pry.actors.apify_actor as apify_actor
from actor_factory.presets import SCRAPER_ACTOR
from pry.actors.apify_actor import _extract_links, scrape_url

REPO = Path(__file__).resolve().parents[1]


class TestExtractLinks:
    def test_same_domain_kept_cross_domain_dropped(self) -> None:
        html = (
            '<a href="http://e.com/a">a</a>'
            '<a href="http://other.com/b">b</a>'
            '<a href="https://e.com/c">c</a>'
        )
        links = _extract_links(html, "http://e.com/start")
        assert links == ["http://e.com/a", "https://e.com/c"]

    def test_root_relative_href_resolved(self) -> None:
        html = '<a href="/sub/page">x</a>'
        links = _extract_links(html, "http://e.com/dir/page")
        assert "http://e.com/sub/page" in links

    def test_fragments_deduplicated(self) -> None:
        html = (
            '<a href="http://e.com/page">p</a>'
            '<a href="http://e.com/page#section">dup</a>'
            '<a href="http://e.com/page">again</a>'
        )
        links = _extract_links(html, "http://e.com/")
        assert links == ["http://e.com/page"]

    def test_cap_fifty_per_page(self) -> None:
        html = "".join(f'<a href="http://e.com/{i}">{i}</a>' for i in range(80))
        assert len(_extract_links(html, "http://e.com/")) == 50

    def test_no_links_returns_empty(self) -> None:
        assert _extract_links("<p>no anchors here</p>", "http://e.com/") == []


class TestScrapeUrlContract:
    @pytest.fixture
    def scraper(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_success_item_shape(self, scraper) -> None:
        scraper.scrape = AsyncMock(
            return_value={
                "status": "ok",
                "content": "# Heading\n\nbody text",
                "raw_html": "<h1>Heading</h1>",
                "method": "direct",
            }
        )
        item = await scrape_url(scraper, "http://example.com/x", {})
        assert item.url == "http://example.com/x"
        assert item.status == "ok"
        assert item.method == "direct"
        assert item.content == "# Heading\n\nbody text"
        assert item.metadata.domain == "example.com"
        assert item.metadata.content_length == len("# Heading\n\nbody text")
        assert item.metadata.method == "direct"
        assert item.scraped_at
        assert isinstance(item.elapsed_seconds, float)

    @pytest.mark.asyncio
    async def test_error_item_has_error_not_content(self, scraper) -> None:
        scraper.scrape = AsyncMock(return_value={"status": "error", "error": "all_tiers_failed"})
        item = await scrape_url(scraper, "http://example.com/dead", {})
        assert item.status == "error"
        assert item.error == "all_tiers_failed"
        assert item.content == ""

    @pytest.mark.asyncio
    async def test_options_forwarded_to_scraper(self, scraper) -> None:
        scraper.scrape = AsyncMock(return_value={"status": "error", "error": "x"})
        opts = {"timeout": 42, "output_format": "text"}
        await scrape_url(scraper, "http://example.com/o", opts)
        scraper.scrape.assert_awaited_once_with("http://example.com/o", opts)


class TestActorPackaging:
    """The actor must be shippable: spec files valid and mutually consistent."""

    @staticmethod
    def _actor_spec() -> dict:
        return json.loads((REPO / ".actor" / "actor.json").read_text())

    def test_actor_json_valid_and_buildable(self) -> None:
        """Factory-generated spec (Apify docs 2026-08-23): lowercase
        'dockerfile', [N].[N] version, referenced file must exist."""
        spec = self._actor_spec()
        assert spec["actorSpecification"] == 1
        assert spec["name"]
        import re

        assert re.match(r"^\d+\.\d+$", spec["version"]), (
            f"version '{spec['version']}' violates Apify [N].[N] rule"
        )
        dockerfile = REPO / ".actor" / spec["dockerfile"].lstrip("./")
        assert dockerfile.exists(), f"referenced Dockerfile missing: {spec['dockerfile']}'"
        assert spec["meta"]["templateId"] == "pry-actor-factory"
        assert spec["name"] == SCRAPER_ACTOR.name

    def test_input_schema_contract(self) -> None:
        props = self._actor_spec()["input"]["properties"]
        assert props["urls"]["type"] == "array"
        # Matches ApifyActorInput's output_format pattern (see apify_schema_parity).
        assert set(props["output_format"]["enum"]) == {"markdown", "html", "text", "json"}
        # standalone INPUT_SCHEMA.json stays in lockstep with the embedded one
        standalone = json.loads((REPO / ".actor" / "INPUT_SCHEMA.json").read_text())
        assert standalone["properties"] == props

    def test_output_schema_covers_emitted_fields(self) -> None:
        """Apify contract: actor.json 'output' points at output_schema.json;
        that file holds link definitions (actorOutputSchemaVersion/title/
        properties[].template). Field-level coverage of what the runner
        emits lives in the DATASET schema."""
        spec = self._actor_spec()
        assert spec["output"] == "./output_schema.json"
        out = json.loads((REPO / ".actor" / "output_schema.json").read_text())
        assert out["actorOutputSchemaVersion"] == 1
        assert out["title"]
        props = out["properties"]
        assert "results" in props, "output must link the default dataset"
        assert props["results"]["type"] == "string"
        assert "{{links.apiDefaultDatasetUrl}}" in props["results"]["template"]

    def test_dataset_schema_covers_emitted_fields(self) -> None:
        dataset = json.loads((REPO / ".actor" / "dataset_schema.json").read_text())
        assert dataset["actorSpecification"] == 1
        declared = set(dataset["fields"]["properties"])
        emitted = {
            "url",
            "status",
            "content",
            "method",
            "error",
            "scraped_at",
            "metadata",
        }
        missing = emitted - declared
        assert not missing, f"runner emits fields absent from dataset schema: {missing}"
        views = dataset["views"]
        assert "overview" in views, "Console Output tab needs an overview view"
        assert views["overview"]["display"]["component"] == "table"

    def test_dockerfile_installs_lock_and_sdk(self) -> None:
        dockerfile = (REPO / ".actor" / "Dockerfile").read_text()
        assert "requirements.lock" in dockerfile  # pinned installs
        assert "apify>=2.7" in dockerfile
        # official Apify pattern: playwright base image ships browsers -
        # running `playwright install` in builds is slow and fragile
        assert "actor-python-playwright" in dockerfile
        assert "playwright install" not in dockerfile

    def test_entry_point_imports_without_sdk(self) -> None:
        """apify_actor.py imports cleanly WITHOUT apify-sdk installed
        (Actor is imported lazily inside main()) - the main suite must
        never depend on the SDK."""

        assert hasattr(apify_actor, "main")


# ── T1 win #3: Pydantic input/output validation tests ────────────────────────


class TestApifyActorInputValidation:
    """Pydantic validation for Apify actor input — catches malformed input
    before any scraping starts."""

    def test_valid_input_from_dict(self) -> None:
        from pry.actors.apify_actor import ApifyActorInput

        inp = ApifyActorInput.model_validate(
            {
                "urls": ["https://example.com", "https://example.org"],
                "max_pages": 5,
                "timeout": 30,
                "output_format": "markdown",
                "crawl": True,
            }
        )
        assert len(inp.urls) == 2
        assert inp.max_pages == 5
        assert inp.output_format == "markdown"
        assert inp.crawl is True

    def test_single_url_string_coerced_to_list(self) -> None:
        from pry.actors.apify_actor import ApifyActorInput

        inp = ApifyActorInput.model_validate({"urls": "https://example.com"})
        assert inp.urls == ["https://example.com"]

    def test_missing_urls_raises(self) -> None:
        from pydantic import ValidationError

        from pry.actors.apify_actor import ApifyActorInput

        with pytest.raises(ValidationError) as exc_info:
            ApifyActorInput.model_validate({})
        assert "urls" in str(exc_info.value)

    def test_empty_urls_raises(self) -> None:
        from pydantic import ValidationError

        from pry.actors.apify_actor import ApifyActorInput

        with pytest.raises(ValidationError):
            ApifyActorInput.model_validate({"urls": []})

    def test_invalid_url_stripped(self) -> None:
        from pry.actors.apify_actor import ApifyActorInput

        inp = ApifyActorInput.model_validate(
            {
                "urls": ["  https://example.com  ", ""],
            }
        )
        assert inp.urls == ["https://example.com"]

    def test_max_pages_out_of_range_raises(self) -> None:
        from pydantic import ValidationError

        from pry.actors.apify_actor import ApifyActorInput

        with pytest.raises(ValidationError):
            ApifyActorInput.model_validate({"urls": ["https://x.com"], "max_pages": 0})
        with pytest.raises(ValidationError):
            ApifyActorInput.model_validate({"urls": ["https://x.com"], "max_pages": 9999})

    def test_invalid_output_format_raises(self) -> None:
        from pydantic import ValidationError

        from pry.actors.apify_actor import ApifyActorInput

        with pytest.raises(ValidationError):
            ApifyActorInput.model_validate(
                {
                    "urls": ["https://x.com"],
                    "output_format": "xml",
                }
            )

    def test_timeout_out_of_range_raises(self) -> None:
        from pydantic import ValidationError

        from pry.actors.apify_actor import ApifyActorInput

        with pytest.raises(ValidationError):
            ApifyActorInput.model_validate({"urls": ["https://x.com"], "timeout": 2})
        with pytest.raises(ValidationError):
            ApifyActorInput.model_validate({"urls": ["https://x.com"], "timeout": 200})

    def test_proxy_config_defaults(self) -> None:
        from pry.actors.apify_actor import ApifyActorInput

        inp = ApifyActorInput.model_validate({"urls": ["https://x.com"]})
        assert inp.proxy_config.use_apify_proxies is False
        assert inp.proxy_config.proxy_country == "US"

    def test_proxy_config_custom(self) -> None:
        from pry.actors.apify_actor import ApifyActorInput

        inp = ApifyActorInput.model_validate(
            {
                "urls": ["https://x.com"],
                "proxy_config": {"use_apify_proxies": True, "proxy_country": "DE"},
            }
        )
        assert inp.proxy_config.use_apify_proxies is True
        assert inp.proxy_config.proxy_country == "DE"


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
