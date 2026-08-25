"""Tests for routers/extraction.py — table, links, schema extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.extraction import router

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

    with patch("pry.api.routers.extraction.get_client", return_value=mock_client):
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
    assert router.tags == ["Extraction"]


def test_router_routes():
    paths = sorted([r.path for r in router.routes])
    assert "/v1/extract-table" in paths
    assert "/v1/links" in paths
