# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Golden-master characterization tests for the three fetch stacks.

Audit win #11 Phase 0: pins the CURRENT observable behaviour of
scraper.py, ultimate_scraper.py and scraping_methods.py so the Phase 1-3
consolidation refactor cannot silently change it. Exact shapes/orders are
asserted on purpose — a failure after refactoring means either behaviour
changed (fix the refactor) or the contract intentionally changed (update
this file in the same PR with a note).

All upstream I/O is mocked; nothing here touches the network.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pry.engine.ultimate_scraper import UltimateScraper

LONG = "<html><body>" + ("lorem ipsum dolor sit amet " * 40) + "</body></html>"


@pytest.fixture
def us() -> UltimateScraper:
    return UltimateScraper()


def _patch_registry() -> list[Any]:
    """Deterministic registry collaborators (no adaptive reordering)."""
    return [
        patch(
            "pry.engine.ultimate_scraper.registry.reorder_for_domain",
            side_effect=lambda _d, chain: chain,
        ),
        patch("pry.engine.ultimate_scraper.registry.is_service_allowed", return_value=True),
        patch("pry.engine.ultimate_scraper.registry.record_domain_tier_result"),
        patch("pry.engine.ultimate_scraper.registry.record_service_result"),
    ]


def _start(patchers: list[Any]) -> ExitStack:
    """Start all patchers under one stack (with *unpacking is not legal syntax)."""
    stack = ExitStack()
    for p in patchers:
        stack.enter_context(p)
    return stack


def _mock_all_tiers(us: UltimateScraper, behavior: dict[str, str | None]) -> list[Any]:
    """Patch every _tier_* method; behavior maps tier-name -> html or None."""
    patchers = []
    for attr in sorted(m for m in dir(us) if m.startswith("_tier_")):
        tier = attr.removeprefix("_tier_")
        html = behavior.get(tier)

        async def _fake(*_a: Any, _html: str | None = html, **_k: Any) -> str | None:
            return _html

        patchers.append(patch.object(us, attr, new=AsyncMock(side_effect=_fake)))
    return patchers


class TestUltimateScraperResultContract:
    """The exact success/error dict shape clients depend on."""

    @pytest.mark.asyncio
    async def test_success_contract_keys(self, us: UltimateScraper) -> None:
        patchers = _patch_registry() + _mock_all_tiers(us, {"direct": LONG})
        with _start(patchers):
            result = await us.scrape("http://example.com/page")
        assert result["status"] == "ok"
        assert result["url"] == "http://example.com/page"
        assert result["method"] == "direct"
        expected = {"status", "url", "raw_html", "method", "content"}
        assert set(result.keys()) == expected
        assert "lorem ipsum" in result["raw_html"]

    @pytest.mark.asyncio
    async def test_error_contract_when_every_tier_fails(self, us: UltimateScraper) -> None:
        patchers = _patch_registry() + _mock_all_tiers(us, {})  # everything None
        with _start(patchers):
            result = await us.scrape("http://example.com/never")
        assert result["status"] == "error"
        assert isinstance(result.get("error"), str)
        assert result["error"]  # non-empty diagnosis

    @pytest.mark.asyncio
    async def test_invalid_url_short_circuits_without_tiers(self, us: UltimateScraper) -> None:
        calls: list[str] = []
        patchers = _patch_registry()
        for attr in sorted(m for m in dir(us) if m.startswith("_tier_")):

            async def _spy(*_a: Any, _attr: str = attr, **_k: Any) -> None:
                calls.append(_attr)
                return None

            patchers.append(patch.object(us, attr, new=AsyncMock(side_effect=_spy)))
        with _start(patchers):
            result = await us.scrape("not-a-url")
        assert result["status"] == "error"
        assert calls == []  # no tier may run for invalid input


class TestUltimateScraperAttemptOrder:
    """Fallback chain order is a client-visible contract (latency + cost)."""

    @pytest.mark.asyncio
    async def test_chain_stops_at_first_valid_content(self, us: UltimateScraper) -> None:
        calls: list[str] = []
        patchers: list[Any] = _patch_registry()
        plan = {
            "direct": None,
            "tls_fingerprint": LONG,
            # everything after must never run:
            "cloudscraper": None,
            # (unreached tiers stay None)
        }
        for attr in sorted(m for m in dir(us) if m.startswith("_tier_")):
            tier = attr.removeprefix("_tier_")
            html = plan.get(tier)

            async def _fake(*_a: Any, _t: str = tier, _h: str | None = html, **_k: Any):
                calls.append(_t)
                return _h

            patchers.append(patch.object(us, attr, new=AsyncMock(side_effect=_fake)))
        with _start(patchers):
            result = await us.scrape("http://example.com/order")
        assert result["method"] == "tls_fingerprint"
        expected = ["direct", "tls_fingerprint"]
        assert calls == expected

    @pytest.mark.asyncio
    async def test_empty_body_is_not_success(self, us: UltimateScraper) -> None:
        calls: list[str] = []
        patchers: list[Any] = _patch_registry()
        plan = {"direct": "", "tls_fingerprint": LONG}
        for attr in sorted(m for m in dir(us) if m.startswith("_tier_")):
            tier = attr.removeprefix("_tier_")
            html = plan.get(tier)

            async def _fake(*_a: Any, _t: str = tier, _h: str | None = html, **_k: Any):
                calls.append(_t)
                return _h

            patchers.append(patch.object(us, attr, new=AsyncMock(side_effect=_fake)))
        with _start(patchers):
            result = await us.scrape("http://example.com/empty")
        expected = ["direct", "tls_fingerprint"]
        assert calls == expected
        assert result["status"] == "ok"


class TestPryScraperDelegation:
    """scraper.py delegates fetching to UltimateScraper, then enriches."""

    @pytest.fixture
    def ps(self):
        from pry.engine.scraper import PryScraper

        s = PryScraper()
        s._ultimate = AsyncMock()
        return s

    @pytest.mark.asyncio
    async def test_invalid_url_error_contract(self, ps) -> None:
        result = await ps.scrape("ftp://nope")
        expected = {
            "status": "error",
            "url": "ftp://nope",
            "error": "Invalid URL",
            "content": "",
        }
        assert result == expected

    @pytest.mark.asyncio
    async def test_upstream_failure_passes_through_untouched(self, ps) -> None:
        ps._ultimate.scrape = AsyncMock(return_value={"status": "error", "error": "dead"})
        result = await ps.scrape("http://example.com/dead")
        expected = {"status": "error", "error": "dead"}
        assert result == expected

    @pytest.mark.asyncio
    async def test_success_enriches_with_quality_and_method(self, ps) -> None:
        html = "<html><title>T</title><p>" + "word " * 200 + "</p></html>"
        ps._ultimate.scrape = AsyncMock(
            return_value={"status": "ok", "raw_html": html, "method": "tor"}
        )
        result = await ps.scrape("http://example.com/enriched")
        assert result["quality_score"] > 0
        assert result["method"] == "tor"
        assert result["raw_html"] == html  # preserved for template engines


class TestScrapingMethodsGolden:
    """Feed/sitemap/discovery utilities against canned XML (no network)."""

    RSS = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>Feed</title>
      <item><title>One</title><link>http://e.com/1</link>
        <description>d1</description><pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate></item>
      <item><title>Two</title><link>http://e.com/2</link></item>
    </channel></rss>"""

    ATOM = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>A1</title><link href="http://a.com/1"/><summary>s1</summary></entry>
      <entry><title>A2</title><link href="http://a.com/2"/><content>c2</content>
        <updated>2026-01-02T00:00:00Z</updated></entry>
    </feed>"""

    SITEMAP = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>http://s.com/b</loc></url>
      <url><loc>http://s.com/a</loc></url>
    </urlset>"""

    def test_rss_entries_exact_shape(self) -> None:
        from pry.engine.scraping_methods import _rss_entries

        entries = _rss_entries(ET.fromstring(self.RSS))  # noqa: S314 - trusted fixture
        expected = [
            {
                "title": "One",
                "link": "http://e.com/1",
                "summary": "d1",
                "published": "Mon, 01 Jan 2026 00:00:00 GMT",
            },
            {"title": "Two", "link": "http://e.com/2", "summary": "", "published": ""},
        ]
        assert entries == expected

    def test_atom_entries_content_and_updated_fallbacks(self) -> None:
        from pry.engine.scraping_methods import _atom_entries

        entries = _atom_entries(ET.fromstring(self.ATOM))  # noqa: S314 - trusted fixture
        expected = {
            "title": "A1",
            "link": "http://a.com/1",
            "summary": "s1",
            "published": "",
        }
        assert entries[0] == expected
        # <content> falls back into summary; <updated> into published.
        assert entries[1]["summary"] == "c2"
        assert entries[1]["published"] == "2026-01-02T00:00:00Z"

    def test_parse_feed_routes_rss_and_atom(self) -> None:
        import pry.engine.methods.feeds as sm

        with patch.object(sm._common, "_sync_get") as get:
            get.return_value.text = self.RSS
            assert sm.parse_feed("http://x/feed.xml")[0]["title"] == "One"
            get.return_value.text = self.ATOM
            assert sm.parse_feed("http://x/atom.xml")[0]["title"] == "A1"
            get.return_value.text = "<html>not a feed</html>"
            assert sm.parse_feed("http://x/nope") == []

    def test_parse_sitemap_dedupes_and_returns_locs(self) -> None:
        import pry.engine.methods.sitemaps as sm

        with patch.object(sm._common, "_sync_get") as get:
            get.return_value.text = self.SITEMAP
            urls = sm.parse_sitemap("http://s.com/sitemap.xml")
        expected = ["http://s.com/a", "http://s.com/b"]
        assert sorted(urls) == expected

    def test_discover_feed_resolves_relative_href(self) -> None:
        from pry.engine.scraping_methods import discover_feed

        html = '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
        assert discover_feed("http://blog.example/post/1", html) == ("http://blog.example/feed.xml")
        assert discover_feed("http://blog.example/post/1", "<html></html>") is None
