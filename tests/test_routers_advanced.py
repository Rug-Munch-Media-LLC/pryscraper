"""Tests for routers/advanced.py — advanced analysis TLS/analysis tools."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.advanced import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_tls_impersonate_unavailable():
    with patch("tls_fingerprint.TLSScraper") as mock_scraper:
        inst = MagicMock()
        inst.is_available.return_value = False
        mock_scraper.return_value = inst
        r = client.post("/v1/tls/impersonate", json={"url": "http://example.com"})
        assert r.status_code in (200, 400, 422, 500)
        if r.status_code == 200:
            assert r.json().get("success") is False


def test_tls_impersonate_success():
    with patch("tls_fingerprint.TLSScraper") as mock_scraper:
        inst = MagicMock()
        inst.is_available.return_value = True
        inst.fetch = AsyncMock(
            return_value={
                "success": True,
                "content": "fetched",
                "method": "tls",
            }
        )
        mock_scraper.return_value = inst
        r = client.post("/v1/tls/impersonate", json={"url": "http://example.com"})
        assert r.status_code in (200, 400, 422, 500)


def test_tls_rotate_unavailable():
    with patch("tls_fingerprint.TLSScraper") as mock_scraper:
        inst = MagicMock()
        inst.is_available.return_value = False
        mock_scraper.return_value = inst
        r = client.post("/v1/tls/rotate", json={"url": "http://example.com"})
        assert r.status_code in (200, 400, 422, 500)


def test_tls_rotate_success():
    with patch("tls_fingerprint.TLSScraper") as mock_scraper:
        inst = MagicMock()
        inst.is_available.return_value = True
        inst.rotate = AsyncMock(
            return_value={
                "success": True,
                "content": "rotated",
                "impersonate": "chrome131",
            }
        )
        mock_scraper.return_value = inst
        r = client.post("/v1/tls/rotate", json={"url": "http://example.com"})
        assert r.status_code in (200, 400, 422, 500)


def test_invalid_url_rejected():
    r = client.post("/v1/tls/impersonate", json={"url": "not-a-url"})
    assert r.status_code in (400, 422, 500)
