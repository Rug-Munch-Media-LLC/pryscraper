"""Tests for routers/export.py — export endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.export import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_export_json():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "ok", "content": "data", "title": "page"}
        r = client.post(
            "/v1/export?format=json",
            content='"http://x.com"',
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True


def test_export_csv():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "ok", "content": "data", "title": "page"}
        r = client.post(
            "/v1/export?format=csv",
            content='"http://x.com"',
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200


def test_export_rss():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "ok", "content": "data", "title": "page"}
        r = client.post(
            "/v1/export?format=rss",
            content='"http://x.com"',
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert "<rss" in r.json()["data"]["rss"]


def test_export_txt():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "ok", "content": "data", "title": "page"}
        r = client.post(
            "/v1/export", content='"http://x.com"', headers={"Content-Type": "application/json"}
        )
        assert r.status_code in (200, 400, 422)


def test_export_scrape_failure():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "error", "error": "fail"}
        r = client.post(
            "/v1/export?format=json",
            content='"http://x.com"',
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code in (400, 422, 500)
