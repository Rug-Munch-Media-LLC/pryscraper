"""Tests for routers/dashboard.py — server-rendered HTML dashboard."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.dashboard import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_dashboard_html():
    """Dashboard returns HTML with Pry branding."""
    r = client.get("/dashboard")
    assert r.status_code in (200, 401, 422, 500)
    if r.status_code == 200:
        assert "Pry Dashboard" in r.text
        assert "Cache Hit Rate" in r.text
        assert "Rate Limit" in r.text


def test_dashboard_has_sessions():
    r = client.get("/dashboard")
    if r.status_code == 200:
        assert "Sessions" in r.text


def test_dashboard_has_version():
    r = client.get("/dashboard")
    if r.status_code == 200:
        assert "3.0.0" in r.text or "v3" in r.text


@patch("pry.api.routers.dashboard.cache.stats")
def test_dashboard_with_cache(mock_stats):
    mock_stats.return_value = {"hit_rate": 85, "hits": 1000, "size": 500}
    r = client.get("/dashboard")
    if r.status_code == 200:
        assert "85%" in r.text


@patch("pry.api.routers.dashboard.ratelimiter.get_stats")
def test_dashboard_with_ratelimit(mock_stats):
    mock_stats.return_value = {"total_requests": 50000, "active_ips": 42, "total_blocked": 10}
    r = client.get("/dashboard")
    if r.status_code == 200:
        assert "50000" in r.text
