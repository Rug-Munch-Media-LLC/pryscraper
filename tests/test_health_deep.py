"""Deep health contract — shape, degradation, readiness, budget, no DSN leak.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import asyncio
import time
from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.core import health
from pry.api.routers.core.health_probes import uptime_seconds


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(health.router)
    return TestClient(app)


def _patched(*, redis_ok: bool = True, db_ok: bool = True) -> ExitStack:
    """Patch the four probes via patch.object (no monkeypatch anti-pattern)."""

    async def _redis() -> bool:
        return redis_ok

    async def _db() -> bool:
        return db_ok

    async def _optional() -> bool:
        return False

    stack = ExitStack()
    stack.enter_context(patch.object(health, "_check_redis", _redis))
    stack.enter_context(patch.object(health, "_check_database", _db))
    stack.enter_context(patch.object(health, "_check_flaresolverr", _optional))
    stack.enter_context(patch.object(health, "_check_ollama", _optional))
    return stack


def test_health_reports_deep_shape() -> None:
    with _patched():
        r = _client().get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert isinstance(body["uptime_seconds"], (int, float))
    assert body["queue_depth"] is None or isinstance(body["queue_depth"], int)
    assert body["dependencies"]["database"] is True
    assert body["services"] == {"database": "up", "redis": "up"}


def test_health_degrades_when_redis_down() -> None:
    with _patched(redis_ok=False):
        r = _client().get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["services"]["redis"] == "degraded"
    assert body["services"]["database"] == "up"


def test_ready_fails_when_database_down() -> None:
    with _patched(db_ok=False):
        r = _client().get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["database"] is False


def test_health_does_not_leak_connection_strings() -> None:
    with _patched():
        raw = _client().get("/health").text
    assert "postgresql" not in raw
    assert "redis://" not in raw
    assert "password" not in raw.lower()


def test_health_probe_budget_is_bounded() -> None:
    async def _slow() -> bool:
        await asyncio.sleep(5)
        return True

    stack = ExitStack()
    for name in ("_check_redis", "_check_database", "_check_flaresolverr", "_check_ollama"):
        stack.enter_context(patch.object(health, name, _slow))
    with stack:
        started = time.monotonic()
        r = _client().get("/health")
        elapsed = time.monotonic() - started
    assert r.status_code == 503
    assert elapsed < 1.5, f"/health exceeded its 1s budget: {elapsed:.2f}s"


def test_uptime_is_monotonic_and_non_negative() -> None:
    first: Any = uptime_seconds()
    assert first >= 0
    assert uptime_seconds() >= first


def test_queue_depth_is_cheap_and_safe() -> None:
    from pry.api.routers.core.health_probes import queue_depth

    depth = queue_depth()
    assert depth is None or depth >= 0
