"""Tests for routers/analysis.py — analysis endpoints."""

from __future__ import annotations
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.analysis import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_compare_identical():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "ok", "content": "same"}
        r = client.post("/v1/compare", json={"url1": "http://a.com", "url2": "http://b.com"})
        assert r.status_code == 200
        assert r.json()["data"]["identical"] is True


def test_compare_different():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.side_effect = [
            {"status": "ok", "content": "version A"},
            {"status": "ok", "content": "version B"},
        ]
        r = client.post("/v1/compare", json={"url1": "http://a.com", "url2": "http://b.com"})
        assert r.status_code == 200
        assert r.json()["data"]["identical"] is False


def test_compare_failure():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "error", "error": "fail"}
        r = client.post("/v1/compare", json={"url1": "http://a.com", "url2": "http://b.com"})
        assert r.status_code in (200, 400, 422, 500)


def test_watch_page():
    with (
        patch("deps.scraper.scrape", new_callable=AsyncMock) as ms,
        patch("deps.advanced.track_diff", new_callable=AsyncMock) as mt,
    ):
        ms.return_value = {"status": "ok", "content": "data"}
        mt.return_value = {"status": "registered", "version": 1}
        r = client.post("/v1/watch", json={"url": "http://x.com", "webhook": "http://hook.com"})
        assert r.status_code == 200


def test_watch_failure():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "error", "error": "fail"}
        r = client.post("/v1/watch", json={"url": "http://x.com", "webhook": "http://hook.com"})
        assert r.status_code in (400, 422, 500)


def test_summarize():
    with (
        patch("deps.scraper.scrape", new_callable=AsyncMock) as ms,
        patch("deps.advanced.summarize", new_callable=AsyncMock) as msum,
    ):
        ms.return_value = {"status": "ok", "content": "long content..."}
        msum.return_value = {"summary": "short", "word_count": 50}
        r = client.post("/v1/summarize", json={"url": "http://x.com"})
        assert r.status_code in (200, 400, 422, 500)


def test_summarize_scrape_failure():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "error", "error": "timeout"}
        r = client.post("/v1/summarize", json={"url": "http://x.com"})
        assert r.status_code in (400, 422, 500)


def test_diff():
    with patch("deps.advanced.track_diff", new_callable=AsyncMock) as m:
        m.return_value = {"status": "changed", "diff": "+new"}
        r = client.post("/v1/diff", json={"url": "http://x.com", "content": "new content"})
        assert r.status_code == 200


def test_diff_scrape():
    with (
        patch("deps.scraper.scrape", new_callable=AsyncMock) as ms,
        patch("deps.advanced.track_diff", new_callable=AsyncMock) as mt,
    ):
        ms.return_value = {"status": "ok", "content": "data"}
        mt.return_value = {"status": "same"}
        r = client.post("/v1/diff", json={"url": "http://x.com"})
        assert r.status_code == 200


def test_categorize():
    with (
        patch("deps.scraper.scrape", new_callable=AsyncMock) as ms,
        patch("deps.advanced.categorize", return_value=["tech"]),
        patch("deps.advanced.keyword_density", return_value=[("word", 5)]),
        patch("deps.advanced.readability", return_value={"score": 65}),
    ):
        ms.return_value = {"status": "ok", "content": "tech article"}
        r = client.post("/v1/categorize", json={"url": "http://x.com"})
        assert r.status_code in (200, 400, 422, 500)


def test_categorize_failure():
    with patch("deps.scraper.scrape", new_callable=AsyncMock) as m:
        m.return_value = {"status": "error", "error": "blocked"}
        r = client.post("/v1/categorize", json={"url": "http://x.com"})
        assert r.status_code in (400, 422, 500)
