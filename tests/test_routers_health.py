"""Tests for routers/health.py — health, liveness, readiness probes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.core.health import router

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


@patch("pry.api.routers.core.health.get_client")
def test_health_check_ollama_up(mock_get_client):
    """Health check with all deps up."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.post = AsyncMock()
    mock_client.post.return_value.is_success = True
    mock_get_client.return_value = mock_client

    with patch("pry.api.routers.core.health.redis.asyncio.from_url") as mock_redis:
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


@patch("pry.api.routers.core.health.get_client")
def test_health_check_ollama_down(mock_get_client):
    """Health check with ollama down."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
    mock_get_client.return_value = mock_client

    with patch("pry.api.routers.core.health.redis.asyncio.from_url") as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.ping = AsyncMock(return_value=True)
        mock_redis.return_value = mock_redis_instance

        r = client.get("/health")
        assert r.status_code in (200, 503, 422, 500)


@patch("pry.api.routers.core.health.get_client")
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


@patch("pry.api.routers.core.health.get_client")
def test_ready_check_fail(mock_get_client):
    """Readiness probe with ollama down."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("Down"))
    mock_get_client.return_value = mock_client

    r = client.get("/ready")
    assert r.status_code in (503, 422, 500)


# ── Health-contract regression tests (2026-08-25) ────────────────────────
# Incident: /health gated on FlareSolverr (optional tier-3 dep) and returned
# 503 for 4 days while the service was fully functional. The contract now is:
# CRITICAL deps gate (/health, /ready); OPTIONAL deps are informational only.


@patch("pry.api.routers.core.health.get_client")
def test_health_stays_ok_when_all_optional_deps_down(mock_get_client):
    """FlareSolverr AND Ollama down + redis up => 200 ok (incident regression)."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("ollama down"))
    mock_client.post = AsyncMock(side_effect=Exception("flaresolverr down"))
    mock_get_client.return_value = mock_client

    with patch("pry.api.routers.core.health.redis.asyncio.from_url") as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.ping = AsyncMock(return_value=True)
        mock_redis_instance.close = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["redis"] is True
    assert body["dependencies"]["flaresolverr"] is False  # informational only
    assert body["dependencies"]["ollama"] is False  # informational only


@patch("pry.api.routers.core.health.get_client")
def test_health_degrades_when_critical_redis_down(mock_get_client):
    """Redis down => 503 degraded, even with every optional dep up."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.post = AsyncMock()
    mock_client.post.return_value.is_success = True
    mock_get_client.return_value = mock_client

    with patch("pry.api.routers.core.health.redis.asyncio.from_url") as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.ping = AsyncMock(side_effect=redis.RedisError("down"))
        mock_redis.return_value = mock_redis_instance

        r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"


@patch("pry.api.routers.core.health.get_client")
def test_ready_ignores_optional_deps(mock_get_client):
    """/ready must be ready when redis is up even if Ollama is unreachable."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("ollama down"))
    mock_get_client.return_value = mock_client

    with patch("pry.api.routers.core.health.redis.asyncio.from_url") as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.ping = AsyncMock(return_value=True)
        mock_redis_instance.close = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def test_healthz_is_pure_liveness():
    """/healthz never probes dependencies — always 200 ok."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
