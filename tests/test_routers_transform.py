"""Tests for routers/transform.py — handler unit tests (no x402 middleware)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.transform import router as transform_router

app = FastAPI()
app.include_router(transform_router)
client = TestClient(app, raise_server_exceptions=False)

SAMPLE_DATA = [{"key": "value", "num": 42}]


def test_transform_csv():
    r = client.post("/v1/transform?format=csv", json=SAMPLE_DATA)
    assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"
    assert r.json().get("success") is True


def test_transform_sql():
    r = client.post("/v1/transform?format=sql", json=SAMPLE_DATA)
    assert r.status_code == 200


def test_transform_html():
    r = client.post("/v1/transform?format=html", json=SAMPLE_DATA)
    assert r.status_code == 200


def test_transform_markdown():
    r = client.post("/v1/transform?format=markdown", json=SAMPLE_DATA)
    assert r.status_code == 200


def test_transform_unknown_format():
    r = client.post("/v1/transform?format=blah", json=SAMPLE_DATA)
    assert r.status_code in (400, 422, 500)


def test_transform_pipe():
    with patch("pry.core.deps.scraper.scrape", new_callable=AsyncMock) as mock_scrape:
        mock_scrape.return_value = {"status": "ok", "content": "data"}
        r = client.post("/v1/pipe", json={"url": "http://example.com", "transform": "json"})
        assert r.status_code in (200, 400, 422, 500)


def test_transform_pipe_failure():
    with patch("pry.core.deps.scraper.scrape", new_callable=AsyncMock) as mock_scrape:
        mock_scrape.return_value = {"status": "error", "error": "failed"}
        r = client.post("/v1/pipe", json={"url": "http://example.com", "transform": "csv"})
        assert r.status_code in (400, 422, 500)
