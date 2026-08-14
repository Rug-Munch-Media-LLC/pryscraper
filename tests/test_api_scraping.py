# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT.
"""End-to-end tests for the scraping router endpoints.

These tests exercise the full FastAPI request/response lifecycle via
TestClient. External I/O (HTTP requests, browser automation) is mocked at the
`deps.scraper` and `deps.extractor` boundaries so tests stay fast and
deterministic.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api import app


@pytest.fixture(autouse=True)
def bypass_x402_middleware() -> Iterator[None]:
    """Disable x402 payment gating so scraping endpoints can be tested."""
    with patch(
        "x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        yield


@pytest.fixture(autouse=True)
def clear_response_cache() -> None:
    """Clear the shared response cache so tests don't see each other's data."""
    from deps import cache as response_cache

    response_cache.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_scrape_result() -> dict:
    return {
        "status": "ok",
        "url": "https://example.com",
        "title": "Example",
        "description": "An example page",
        "content": "Hello world",
        "markdown": "# Hello world",
        "raw_html": "<html><body>Hello world</body></html>",
        "links": ["https://example.com/a", "https://example.com/b"],
    }


@pytest.mark.asyncio
async def test_v1_scrape_success(client: TestClient, mock_scrape_result: dict) -> None:
    with patch("routers.scraping.scraper") as mock_scraper:
        mock_scraper.scrape = AsyncMock(return_value=mock_scrape_result)
        resp = client.post("/v1/scrape", json={"url": "https://example.com"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["metadata"]["url"] == "https://example.com"
    assert data["data"]["markdown"] == "Hello world"


@pytest.mark.asyncio
async def test_v1_scrape_with_json_schema(client: TestClient, mock_scrape_result: dict) -> None:
    schema = {"title": "page title"}
    extracted = {"title": "Example"}
    with (
        patch("routers.scraping.scraper") as mock_scraper,
        patch("routers.scraping.extractor") as mock_extractor,
    ):
        mock_scraper.scrape = AsyncMock(return_value=mock_scrape_result)
        mock_extractor.extract = AsyncMock(return_value=extracted)
        resp = client.post("/v1/scrape", json={"url": "https://example.com", "jsonSchema": schema})

    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["json"] == extracted


@pytest.mark.asyncio
async def test_v1_detect_block_success(client: TestClient) -> None:
    html = "<html><body>ok</body></html>"
    with patch("routers.scraping.get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value=AsyncMock(
                text=html,
                status_code=200,
                headers={"content-type": "text/html"},
            )
        )
        mock_get_client.return_value = mock_client
        resp = client.post(
            "/v1/detect-block",
            content='"https://example.com"',
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["url"] == "https://example.com"
    assert any(r["method"] == "direct" for r in data["data"]["results"])


@pytest.mark.asyncio
async def test_v1_capture_lazy_success(client: TestClient, mock_scrape_result: dict) -> None:
    with patch("routers.scraping.scraper") as mock_scraper:
        mock_scraper.scrape = AsyncMock(return_value=mock_scrape_result)
        resp = client.post("/v1/capture/lazy", json={"url": "https://example.com"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "detection" in data["data"]
    assert "has_lazy_content" in data["data"]


@pytest.mark.asyncio
async def test_v1_crawl_success(client: TestClient, mock_scrape_result: dict) -> None:
    pages = [mock_scrape_result]
    with patch("routers.scraping.scraper") as mock_scraper:
        mock_scraper.crawl = AsyncMock(return_value=pages)
        resp = client.post(
            "/v1/crawl", json={"url": "https://example.com", "maxPages": 2, "maxDepth": 1}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "pages" in data["data"]
    assert data["data"]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_v1_map_success(client: TestClient) -> None:
    urls = ["https://example.com/page1", "https://example.com/page2"]
    with patch("routers.scraping.scraper") as mock_scraper:
        mock_scraper.map_urls = AsyncMock(return_value=urls)
        resp = client.post("/v1/map", json={"url": "https://example.com", "limit": 10})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["links"] == urls


@pytest.mark.asyncio
async def test_v1_batch_success(client: TestClient, mock_scrape_result: dict) -> None:
    urls = ["https://example.com/1", "https://example.com/2"]
    with patch("routers.scraping.scraper") as mock_scraper:
        mock_scraper.scrape = AsyncMock(return_value=mock_scrape_result)
        resp = client.post("/v1/batch", json=urls)

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["pages"]) == len(urls)


@pytest.mark.asyncio
async def test_v1_batch_requires_urls(client: TestClient) -> None:
    resp = client.post("/v1/batch", json={"not_a_list": True})
    assert resp.status_code == 422
