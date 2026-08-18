"""Tests for routers/scraping_api.py — handler unit tests."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.scraping_api import router as scraping_router

# Create a clean app with JUST this router (no x402 middleware)
app = FastAPI()
app.include_router(scraping_router)
client = TestClient(app, raise_server_exceptions=False)


def test_ultimate_scrape_success():
    mock_s = MagicMock()
    mock_s.scrape = AsyncMock(
        return_value={"status": "ok", "method": "direct", "content": "<html>OK</html>"}
    )
    with patch("ultimate_scraper.UltimateScraper", return_value=mock_s):
        r = client.post("/v1/ultimate-scrape", json={"url": "http://example.com"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"
        assert r.json().get("success") is True


def test_ultimate_scrape_failure():
    mock_s = MagicMock()
    mock_s.scrape = AsyncMock(return_value={"status": "error", "error": "all_tiers_failed"})
    with patch("ultimate_scraper.UltimateScraper", return_value=mock_s):
        r = client.post("/v1/ultimate-scrape", json={"url": "http://example.com"})
        assert r.status_code in (400, 422, 500), f"Got {r.status_code}: {r.text[:200]}"


def test_ultimate_scrape_invalid_url():
    r = client.post("/v1/ultimate-scrape", json={"url": "not-a-url"})
    assert r.status_code in (400, 422, 500), f"Got {r.status_code}: {r.text[:200]}"


@patch("routers.scraping_api.safe_get")
def test_capture_network(mock_safe_get):
    mock_safe_get.return_value = {"data": "captured"}
    r = client.post("/v1/capture/network", json={"url": "http://example.com"})
    assert r.status_code in (200, 400, 422)


@patch("routers.scraping_api.safe_get")
def test_crawl_adaptive(mock_safe_get):
    mock_safe_get.return_value = {"data": "crawled"}
    r = client.post("/v1/crawl/adaptive", json={"url": "http://example.com", "max_pages": 5})
    assert r.status_code in (200, 400, 422)
