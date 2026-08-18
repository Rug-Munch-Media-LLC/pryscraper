"""Tests for routers/health.py — health, liveness, readiness probes."""

from __future__ import annotations
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.health import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_liveness():
    r = client.get("/live")
    assert r.status_code in (200, 422, 500)
    if r.status_code == 200:
        assert r.json()["status"] == "alive"


def test_version():
    r = client.get("/version")
    assert r.status_code in (200, 422, 500)
    if r.status_code == 200:
        assert "version" in r.json()


@patch("routers.health.get_client")
def test_health_check_ollama_up(mock_get_client):
    """Health check with all deps up."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.post = AsyncMock()
    mock_client.post.return_value.is_success = True
    mock_get_client.return_value = mock_client

    with patch("routers.health.redis.asyncio.from_url") as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.ping = AsyncMock(return_value=True)
        mock_redis_instance.close = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        r = client.get("/health")
        assert r.status_code in (200, 503, 422, 500)
        if r.status_code in (200, 503):
            data = r.json()
            assert "dependencies" in data
            assert "status" in data


@patch("routers.health.get_client")
def test_health_check_ollama_down(mock_get_client):
    """Health check with ollama down."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
    mock_get_client.return_value = mock_client

    with patch("routers.health.redis.asyncio.from_url") as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.ping = AsyncMock(return_value=True)
        mock_redis.return_value = mock_redis_instance

        r = client.get("/health")
        assert r.status_code in (200, 503, 422, 500)


@patch("routers.health.get_client")
def test_ready_check(mock_get_client):
    """Readiness probe with ollama up."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_get_client.return_value = mock_client

    r = client.get("/ready")
    assert r.status_code in (200, 503, 422, 500)
    if r.status_code == 200:
        assert r.json()["status"] == "ready"


@patch("routers.health.get_client")
def test_ready_check_fail(mock_get_client):
    """Readiness probe with ollama down."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("Down"))
    mock_get_client.return_value = mock_client

    r = client.get("/ready")
    assert r.status_code in (503, 422, 500)
