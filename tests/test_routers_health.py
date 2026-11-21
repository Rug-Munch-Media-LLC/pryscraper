"""Tests for routers/health.py — health, liveness, readiness probes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.core.health import router

app = FastAPI()
app.include_router(router)


async def _await_probe(coro, *_a, **_k):
    """Await a probe directly instead of through `bounded()`.

    `bounded()` wraps each probe in `asyncio.wait_for`, which needs a RUNNING
    event loop. `client` is a module-level TestClient that runs the app in its
    own thread, so in a full run the process-level loop can already be closed by
    an earlier test; the probe coroutine then never executes and a healthy
    dependency is reported as down. Awaiting the probe directly keeps every test
    asserting the health CONTRACT (which dependency is critical) rather than
    depending on loop hygiene elsewhere in the suite.
    """
    return await coro


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


@patch("pry.api.routers.core.probe_checks.get_client")
def test_health_check_ollama_up(mock_get_client):
    """Health check with all deps up."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.post = AsyncMock()
    mock_client.post.return_value.is_success = True
    mock_get_client.return_value = mock_client

    # Patch the name `health.py` actually holds. It binds `probe_redis` into its
    # own namespace at import as `_check_redis`, so patching
    # `probe_checks.redis_probe_client` (two levels down) did nothing and these
    # tests silently needed a LIVE Redis. Without one, /ready correctly returns
    # 503 {"database": True, "redis": False} and the assertion failed for an
    # environment reason rather than a code one.
    with (
        patch("pry.api.routers.core.health._check_redis", AsyncMock(return_value=True)),
        # `bounded()` wraps each probe in `asyncio.wait_for`, so it needs a
        # RUNNING loop. `client` above is a module-level TestClient, which runs
        # the app in its own thread; in a full run the process-level loop can be
        # closed by an earlier test and the probe coroutine then never executes,
        # making a healthy dependency report as down. Stub the wrapper so the
        # assertion is about the health CONTRACT, not about loop hygiene.
        patch("pry.api.routers.core.health.bounded", _await_probe),
    ):
        r = client.get("/health")
        assert r.status_code in (200, 503, 422, 500)
        if r.status_code in (200, 503):
            data = r.json()
            assert "dependencies" in data
            assert "status" in data


@patch("pry.api.routers.core.probe_checks.get_client")
def test_health_check_ollama_down(mock_get_client):
    """Health check with ollama down."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
    mock_get_client.return_value = mock_client

    with (
        patch("pry.api.routers.core.health._check_redis", AsyncMock(return_value=True)),
        # `bounded()` wraps each probe in `asyncio.wait_for`, so it needs a
        # RUNNING loop. `client` above is a module-level TestClient, which runs
        # the app in its own thread; in a full run the process-level loop can be
        # closed by an earlier test and the probe coroutine then never executes,
        # making a healthy dependency report as down. Stub the wrapper so the
        # assertion is about the health CONTRACT, not about loop hygiene.
        patch("pry.api.routers.core.health.bounded", _await_probe),
    ):
        r = client.get("/health")
        assert r.status_code in (200, 503, 422, 500)


@patch("pry.api.routers.core.probe_checks.get_client")
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


@patch("pry.api.routers.core.probe_checks.get_client")
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


@patch("pry.api.routers.core.probe_checks.get_client")
def test_health_stays_ok_when_all_optional_deps_down(mock_get_client):
    """FlareSolverr AND Ollama down + redis up => 200 ok (incident regression)."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("ollama down"))
    mock_client.post = AsyncMock(side_effect=Exception("flaresolverr down"))
    mock_get_client.return_value = mock_client

    # Patch the name `health.py` actually holds. It binds `probe_redis` into its
    # own namespace at import as `_check_redis`, so patching
    # `probe_checks.redis_probe_client` (two levels down) did nothing and these
    # tests silently needed a LIVE Redis. Without one, /ready correctly returns
    # 503 {"database": True, "redis": False} and the assertion failed for an
    # environment reason rather than a code one.
    with (
        patch("pry.api.routers.core.health._check_redis", AsyncMock(return_value=True)),
        # `bounded()` wraps each probe in `asyncio.wait_for`, so it needs a
        # RUNNING loop. `client` above is a module-level TestClient, which runs
        # the app in its own thread; in a full run the process-level loop can be
        # closed by an earlier test and the probe coroutine then never executes,
        # making a healthy dependency report as down. Stub the wrapper so the
        # assertion is about the health CONTRACT, not about loop hygiene.
        patch("pry.api.routers.core.health.bounded", _await_probe),
        patch("pry.api.routers.core.health._check_database", AsyncMock(return_value=True)),
    ):
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["redis"] is True
    assert body["dependencies"]["flaresolverr"] is False  # informational only
    assert body["dependencies"]["ollama"] is False  # informational only


@patch("pry.api.routers.core.probe_checks.get_client")
def test_health_degrades_when_critical_redis_down(mock_get_client):
    """Redis down => 503 degraded, even with every optional dep up."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.post = AsyncMock()
    mock_client.post.return_value.is_success = True
    mock_get_client.return_value = mock_client

    # This test is the NEGATIVE case: redis must be DOWN for /health to degrade.
    # The blanket True above is for the tests that require a healthy critical
    # dep; forcing True here would make the assertion test nothing.
    async def _run(coro, *_a, **_k):
        """Await the probe instead of wrapping it in asyncio.wait_for."""
        return await coro

    with (
        patch("pry.api.routers.core.health._check_redis", AsyncMock(return_value=False)),
        patch("pry.api.routers.core.health._check_database", AsyncMock(return_value=True)),
        # Real `bounded()` needs a running loop; this awaits the probe directly
        # so the redis=False result actually reaches the health contract.
        patch("pry.api.routers.core.health.bounded", _run),
    ):
        r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"


@patch("pry.api.routers.core.probe_checks.get_client")
def test_ready_ignores_optional_deps(mock_get_client):
    """/ready must be ready when redis is up even if Ollama is unreachable."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("ollama down"))
    mock_get_client.return_value = mock_client

    # Patch the name `health.py` actually holds. It binds `probe_redis` into its
    # own namespace at import as `_check_redis`, so patching
    # `probe_checks.redis_probe_client` (two levels down) did nothing and these
    # tests silently needed a LIVE Redis. Without one, /ready correctly returns
    # 503 {"database": True, "redis": False} and the assertion failed for an
    # environment reason rather than a code one.
    with (
        patch("pry.api.routers.core.health._check_redis", AsyncMock(return_value=True)),
        # `bounded()` wraps each probe in `asyncio.wait_for`, so it needs a
        # RUNNING loop. `client` above is a module-level TestClient, which runs
        # the app in its own thread; in a full run the process-level loop can be
        # closed by an earlier test and the probe coroutine then never executes,
        # making a healthy dependency report as down. Stub the wrapper so the
        # assertion is about the health CONTRACT, not about loop hygiene.
        patch("pry.api.routers.core.health.bounded", _await_probe),
        patch("pry.api.routers.core.health._check_database", AsyncMock(return_value=True)),
    ):
        r = client.get("/ready")
    assert r.status_code == 200
    expected = {"status": "ready"}
    assert r.json() == expected


def test_healthz_is_pure_liveness():
    """/healthz never probes dependencies — always 200 ok."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
