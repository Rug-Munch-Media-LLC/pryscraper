"""Tests for the Firecrawl-parity wins: scrape formats, map filters, search scrapeOptions.

Every test drives the real FastAPI app through TestClient; only the external
boundaries (``scraper``, ``safe_get``, ``search_web``) are patched, so the
assertions cover the router logic that ships.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app

if TYPE_CHECKING:
    from collections.abc import Iterator

SCRAPING = "pry.api.routers.scraping.scraping"
SEARCH_MAP = "pry.api.routers.scraping.search_map"

HTML = """<html><head><title>Example</title></head><body>
<article><h1>Hello</h1><p>Body text.</p></article>
<a href="/a">A</a><a href="https://other.example/b">B</a><a href="/a">dup</a>
<img src="/img/x.png"><img src="data:image/png;base64,AAA">
<a href="mailto:x@example.com">mail</a>
</body></html>"""

RESULT: dict[str, Any] = {
    "status": "ok",
    "url": "https://example.com",
    "title": "Example",
    "description": "An example page",
    "content": "# Hello\n\nBody text.",
    "raw_html": HTML,
    "method": "direct",
    "markdown_quality": 0.9,
}


@pytest.fixture(autouse=True)
def bypass_x402_middleware() -> Iterator[None]:
    with patch(
        "pry.payments.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        yield


@pytest.fixture(autouse=True)
def clear_response_cache() -> Iterator[None]:
    from pry.core.deps import cache as response_cache

    response_cache.clear()
    yield
    response_cache.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _scrape_post(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    with patch(f"{SCRAPING}.scraper.scrape", AsyncMock(return_value=dict(RESULT))):
        response = client.post("/v1/scrape", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# ── /v1/scrape formats ──────────────────────────────────────────────────
def test_scrape_returns_requested_formats(client: TestClient) -> None:
    body = _scrape_post(
        client,
        {
            "url": "https://example.com",
            "formats": ["markdown", "html", "rawHtml", "links", "images"],
        },
    )
    data = body["data"]
    assert data["markdown"] == "# Hello\n\nBody text."
    assert data["rawHtml"] == HTML
    assert data["html"]
    assert data["links"] == ["https://example.com/a", "https://other.example/b"]
    # data: URIs are real image sources and are kept; mailto: is not a link.
    assert data["images"] == [
        "https://example.com/img/x.png",
        "data:image/png;base64,AAA",
    ]
    assert data["metadata"]["formats"] == ["html", "images", "links", "markdown", "rawHtml"]


def test_scrape_without_formats_is_markdown_only(client: TestClient) -> None:
    data = _scrape_post(client, {"url": "https://example.com"})["data"]
    assert data["markdown"]
    for absent in ("html", "rawHtml", "links", "images"):
        assert absent not in data


def test_scrape_formats_are_part_of_the_cache_identity(client: TestClient) -> None:
    with patch(f"{SCRAPING}.scraper.scrape", AsyncMock(return_value=dict(RESULT))) as scrape:
        assert client.post("/v1/scrape", json={"url": "https://example.com"}).status_code == 200
        assert (
            client.post(
                "/v1/scrape",
                json={"url": "https://example.com", "formats": ["links"]},
            ).status_code
            == 200
        )
    # Different format set must not be served from the markdown-only entry.
    assert scrape.await_count == 2


# ── /v1/map filters ─────────────────────────────────────────────────────
SITEMAP = """<?xml version="1.0"?><urlset>
    <url><loc>https://example.com/docs/intro</loc></url>
    <url><loc>https://example.com/docs/api</loc></url>
    <url><loc>https://example.com/blog/post</loc></url>
</urlset>"""


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


def test_map_search_filters_urls(client: TestClient) -> None:
    with (
        patch(f"{SEARCH_MAP}.validate_url_async", AsyncMock(side_effect=lambda u: u)),
        patch(f"{SEARCH_MAP}.safe_get", AsyncMock(return_value=_FakeResponse(SITEMAP))),
    ):
        response = client.post("/v1/map", json={"url": "https://example.com", "search": "docs"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert [link["url"] for link in body["links"]] == [
        "https://example.com/docs/intro",
        "https://example.com/docs/api",
    ]


def test_map_sitemap_only_never_crawls(client: TestClient) -> None:
    crawl = AsyncMock(return_value=["https://example.com/fallback"])
    with (
        patch(f"{SEARCH_MAP}.validate_url_async", AsyncMock(side_effect=lambda u: u)),
        patch(f"{SEARCH_MAP}.safe_get", AsyncMock(return_value=_FakeResponse("<urlset/>"))),
        patch(f"{SEARCH_MAP}._legacy_scraping.scraper.map_urls", crawl),
    ):
        response = client.post("/v1/map", json={"url": "https://example.com", "sitemapOnly": True})
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 0
    crawl.assert_not_awaited()


def test_map_ignore_sitemap_skips_sitemap_fetch(client: TestClient) -> None:
    crawl = AsyncMock(return_value=["https://example.com/from-crawl"])
    with (
        patch(f"{SEARCH_MAP}.validate_url_async", AsyncMock(side_effect=lambda u: u)),
        patch(f"{SEARCH_MAP}.safe_get", AsyncMock()) as safe_get,
        patch(f"{SEARCH_MAP}._legacy_scraping.scraper.map_urls", crawl),
    ):
        response = client.post(
            "/v1/map", json={"url": "https://example.com", "ignoreSitemap": True}
        )
    assert response.status_code == 200, response.text
    assert [link["url"] for link in response.json()["links"]] == ["https://example.com/from-crawl"]
    safe_get.assert_not_awaited()


# ── /v1/search scrapeOptions + sources ──────────────────────────────────
def test_search_scrape_options_returns_markdown(client: TestClient) -> None:
    payload = {
        "results": [
            {
                "url": "https://example.com/a",
                "title": "A",
                "snippet": "first",
                "markdown": "# A\n\nscraped",
            }
        ]
    }
    with patch(f"{SEARCH_MAP}.search_and_scrape", AsyncMock(return_value=payload)) as scrape:
        response = client.post(
            "/v1/search",
            json={
                "query": "pry",
                "limit": 1,
                "scrapeOptions": {"formats": ["markdown"]},
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["markdown"] == "# A\n\nscraped"
    scrape.assert_awaited_once()


def test_search_rejects_unimplemented_sources(client: TestClient) -> None:
    response = client.post("/v1/search", json={"query": "pry", "sources": ["news"]})
    assert response.status_code == 400
    assert "news" in response.text


def test_search_plain_does_not_scrape(client: TestClient) -> None:
    payload = {"results": [{"url": "https://e.com", "title": "E", "snippet": "s"}]}
    with (
        patch(f"{SEARCH_MAP}.search_web", AsyncMock(return_value=payload)),
        patch(f"{SEARCH_MAP}.search_and_scrape", AsyncMock()) as scrape,
    ):
        response = client.post("/v1/search", json={"query": "pry"})
    assert response.status_code == 200, response.text
    assert "markdown" not in response.json()["results"][0]
    scrape.assert_not_awaited()
