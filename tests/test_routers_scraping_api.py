"""Tests for routers/scraping_api.py — handler unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.scraping.scraping_api import router as scraping_router

# Create a clean app with JUST this router (no x402 middleware)
app = FastAPI()
app.include_router(scraping_router)
client = TestClient(app, raise_server_exceptions=False)


def test_ultimate_scrape_success():
    mock_s = MagicMock()
    mock_s.scrape = AsyncMock(
        return_value={"status": "ok", "method": "direct", "content": "<html>OK</html>"}
    )
    with patch("pry.engine.ultimate_scraper.UltimateScraper", return_value=mock_s):
        r = client.post("/v1/ultimate-scrape", json={"url": "http://example.com"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"
        assert r.json().get("success") is True


def test_ultimate_scrape_failure():
    mock_s = MagicMock()
    mock_s.scrape = AsyncMock(return_value={"status": "error", "error": "all_tiers_failed"})
    with patch("pry.engine.ultimate_scraper.UltimateScraper", return_value=mock_s):
        r = client.post("/v1/ultimate-scrape", json={"url": "http://example.com"})
        assert r.status_code in (400, 422, 500), f"Got {r.status_code}: {r.text[:200]}"


def test_ultimate_scrape_invalid_url():
    r = client.post("/v1/ultimate-scrape", json={"url": "not-a-url"})
    assert r.status_code in (400, 422, 500), f"Got {r.status_code}: {r.text[:200]}"


@patch("pry.api.routers.scraping.scraping_api.safe_get")
def test_capture_network(mock_safe_get):
    mock_safe_get.return_value = {"data": "captured"}
    r = client.post("/v1/capture/network", json={"url": "http://example.com"})
    assert r.status_code in (200, 400, 422)


@patch("pry.api.routers.scraping.scraping_api.safe_get")
def test_capture_network_success(mock_safe_get):
    """Success path: raw string body + mocked scraper => structured network data."""
    with patch(
        "pry.api.routers.scraping.scraping_api.scraper.scrape", new_callable=AsyncMock
    ) as mock_scrape:
        mock_scrape.return_value = {
            "status": "ok",
            "raw_html": '<html><script src="/api/x"></script></html>',
        }
        r = client.post(
            "/v1/capture/network",
            content='"http://example.com"',
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    data = body["data"]
    assert data["url"] == "http://example.com"
    # Every network-extraction field must be present with the right type.
    assert isinstance(data["api_calls"], list)
    assert isinstance(data["graphql_queries"], list)
    assert isinstance(data["json_ld"], list)
    assert isinstance(data["nextjs_props"], bool)
    assert isinstance(data["nuxt_state"], bool)


@patch("pry.api.routers.scraping.scraping_api.safe_get")
def test_crawl_adaptive(mock_safe_get):
    mock_safe_get.return_value = {"data": "crawled"}
    r = client.post("/v1/crawl/adaptive", json={"url": "http://example.com", "max_pages": 5})
    assert r.status_code in (200, 400, 422)


@patch("pry.api.routers.scraping.scraping_api.safe_get")
def test_crawl_adaptive_success(mock_safe_get):
    """Success path: mocked scraper => adaptive crawl returns pages + stats."""
    with (
        patch(
            "pry.api.routers.scraping.scraping_api.scraper.scrape", new_callable=AsyncMock
        ) as mock_scrape,
        patch(
            "pry.api.routers.scraping.scraping_api.scraper.map_urls", new_callable=AsyncMock
        ) as mock_map,
    ):
        mock_scrape.return_value = {"status": "ok", "content": "hello world"}
        mock_map.return_value = []
        r = client.post("/v1/crawl/adaptive", json={"url": "http://example.com", "max_pages": 5})
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    data = body["data"]
    assert data["url"] == "http://example.com"
    assert isinstance(data["pages"], list)
    assert len(data["pages"]) >= 1
    assert data["total_pages"] == len(data["pages"])
    assert isinstance(data["stats"], dict)
    assert data["stats"]["pages_crawled"] == len(data["pages"])
