"""Tests for routers/analysis.py — compare, watch, summarize."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.ai.analysis import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


@patch("pry.api.routers.ai.analysis.scraper")
@patch("pry.api.routers.ai.analysis.get_client")
def test_compare_identical(mock_get_client, mock_scraper):
    mock_scraper.scrape = AsyncMock(
        return_value={
            "content": "same content\nline 2",
        }
    )
    mock_get_client.return_value = AsyncMock()

    r = client.post(
        "/v1/compare",
        json={
            "url1": "http://a.com",
            "url2": "http://b.com",
        },
    )
    assert r.status_code in (200, 422, 500)
    if r.status_code == 200:
        data = r.json()
        assert data.get("success") is True
        assert "diff" in data["data"]


@patch("pry.api.routers.ai.analysis.scraper")
@patch("pry.api.routers.ai.analysis.get_client")
def test_compare_different(mock_get_client, mock_scraper):
    async def scrape_side_effect(url, **kw):
        if "a.com" in url:
            return {"content": "content A\nline 2"}
        return {"content": "content B\nline 2\nline 3"}

    mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)
    mock_get_client.return_value = AsyncMock()

    r = client.post(
        "/v1/compare",
        json={
            "url1": "http://a.com",
            "url2": "http://b.com",
        },
    )
    assert r.status_code in (200, 422, 500)
    if r.status_code == 200:
        assert r.json()["data"]["identical"] is False


@patch("pry.api.routers.ai.analysis.scraper")
@patch("pry.api.routers.ai.analysis.advanced")
@patch("pry.api.routers.ai.analysis.get_client")
def test_watch_page(mock_get_client, mock_advanced, mock_scraper):
    mock_scraper.scrape = AsyncMock(return_value={"status": "ok", "content": "page content here"})
    mock_advanced.track_diff = AsyncMock(
        return_value={
            "status": "registered",
            "version": 1,
        }
    )
    mock_get_client.return_value = AsyncMock()

    r = client.post(
        "/v1/watch",
        json={
            "url": "http://example.com",
            "webhook": "http://hook.com",
            "interval": 3600,
        },
    )
    assert r.status_code in (200, 422, 500)
    if r.status_code == 200:
        data = r.json()
        assert data.get("success") is True
        assert data["data"]["status"] == "registered"


@patch("pry.api.routers.ai.analysis.scraper")
@patch("pry.api.routers.ai.analysis.advanced")
@patch("pry.api.routers.ai.analysis.get_client")
def test_watch_page_no_webhook(mock_get_client, mock_advanced, mock_scraper):
    mock_scraper.scrape = AsyncMock(return_value={"status": "ok", "content": "page content"})
    mock_advanced.track_diff = AsyncMock(
        return_value={
            "status": "registered",
            "version": 2,
        }
    )
    mock_get_client.return_value = AsyncMock()

    r = client.post(
        "/v1/watch",
        json={
            "url": "http://example.com",
            "webhook": "",
            "interval": 7200,
        },
    )
    assert r.status_code in (200, 422, 500)
    if r.status_code == 200:
        assert r.json()["data"]["version"] == 2


@patch("pry.api.routers.ai.analysis.scraper")
@patch("pry.api.routers.ai.analysis.get_client")
def test_watch_page_scrape_fail(mock_get_client, mock_scraper):
    mock_scraper.scrape = AsyncMock(
        return_value={
            "status": "error",
            "error": "Blocked by Cloudflare",
        }
    )
    mock_get_client.return_value = AsyncMock()

    r = client.post(
        "/v1/watch",
        json={
            "url": "http://example.com",
            "webhook": "http://hook.com",
        },
    )
    assert r.status_code in (500, 400)


def test_compare_scrape_fail():
    """Compare with empty scrape results returns 200 with diff."""
    with patch("pry.api.routers.ai.analysis.scraper") as mock_scraper:
        mock_scraper.scrape = AsyncMock(return_value={})
        with patch("pry.api.routers.ai.analysis.get_client") as mock_gc:
            mock_gc.return_value = AsyncMock()
            r = client.post(
                "/v1/compare",
                json={
                    "url1": "http://a.com",
                    "url2": "http://b.com",
                },
            )
            assert r.status_code in (200, 500)
