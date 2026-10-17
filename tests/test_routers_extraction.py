"""Tests for routers/extraction.py — table, links, schema extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.scraping.extraction import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


# ── extract_table ──


def test_extract_table():
    """Test table extraction from HTML."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.get.return_value.text = (
        "<html><body><table><tr><th>Name</th></tr><tr><td>Alice</td></tr></table></body></html>"
    )
    mock_client.get.return_value.status_code = 200

    with patch("pry.api.routers.scraping.extraction.get_client", return_value=mock_client):
        r = client.post(
            "/v1/extract-table",
            json={
                "url": "http://example.com",
                "table_index": 0,
            },
        )
        assert r.status_code in (200, 422, 500)
        if r.status_code == 200:
            data = r.json()
            assert data.get("success") is True
            assert len(data["data"]["rows"]) > 0


def test_router_tags():
    expected = ["Extraction"]
    assert router.tags == expected


def test_router_routes():
    paths = sorted([r.path for r in router.routes])
    assert "/v1/extract-table" in paths
    assert "/v1/links" in paths


# ── extract_thumbnail: a transport failure must not look like "no thumbnail" ──


def test_extract_thumbnail_transport_failure_is_not_reported_as_no_thumbnail():
    """A scrape failure must be distinguishable from a page with no thumbnail.

    Regression: the failure path used to return ``{"success": False, "data":
    {"thumbnail": None}}`` — byte-identical to the legitimate "page has no
    og:image / twitter:image / img" result — so a caller could not tell a
    transport error from a real absence.
    """
    boom = AsyncMock(side_effect=RuntimeError("upstream unreachable"))

    with patch("pry.api.routers.scraping.extraction.scraper") as mock_scraper:
        mock_scraper.scrape = boom
        r = client.post("/v1/thumbnail", json="http://example.com")

    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is False
    assert body.get("error") == "thumbnail extraction failed"


def test_extract_thumbnail_page_without_image_still_succeeds():
    """The legitimate empty case keeps its shape: success, no error, no thumbnail."""
    mock_scraper = AsyncMock()
    mock_scraper.scrape = AsyncMock(
        return_value={"raw_html": "<html><body>no images</body></html>"}
    )

    with patch("pry.api.routers.scraping.extraction.scraper", mock_scraper):
        r = client.post("/v1/thumbnail", json="http://example.com")

    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert "error" not in body
    assert body["data"]["thumbnail"] is None
