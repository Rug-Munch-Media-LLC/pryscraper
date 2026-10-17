# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""End-to-end critical paths: one test per flow that would page us."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app
from pry.core import api_keys_service

if TYPE_CHECKING:
    from collections.abc import Iterator

X402_CALL = "pry.payments.x402_middleware.X402Middleware.__call__"
SCRAPING = "pry.api.routers.scraping.scraping.scraper"


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[None]:
    """Per-test SQLite DB, data dir and cache so nothing leaks between tests."""
    import pry.core.db as db_module
    import pry.core.db.session as session_mod

    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/e2e.db")
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    db_module._engine = None
    session_mod._engine = None
    session_mod._SessionLocal = None
    db_module.get_engine()
    from pry.core.deps import cache as response_cache

    response_cache.clear()
    yield
    db_module._engine = None
    session_mod._engine = None
    session_mod._SessionLocal = None


@pytest.fixture
def client() -> Iterator[TestClient]:
    bypass = patch(X402_CALL, lambda self, scope, receive, send: self.app(scope, receive, send))
    with bypass, TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def test_health_reports_ready_when_critical_deps_up(client: TestClient) -> None:
    import pry.api.routers.core.health as health

    with (
        patch.object(health, "_check_redis", AsyncMock(return_value=True)),
        patch.object(health, "_check_database", AsyncMock(return_value=True)),
        patch.object(health, "_check_flaresolverr", AsyncMock(return_value=False)),
        patch.object(health, "_check_ollama", AsyncMock(return_value=False)),
    ):
        response = client.get("/health")
    assert response.status_code == 200, response.text
    body = response.json()
    deps = body["dependencies"]
    assert body["status"] == "ok"
    assert deps["redis"]
    assert deps["database"]


def test_app_gate_rejects_non_loopback_peer() -> None:
    with TestClient(app, client=("203.0.113.9", 51234)) as external:
        response = external.get("/app")
    assert response.status_code in (401, 403), response.text


def test_app_key_create_then_revoke(client: TestClient) -> None:
    from pry.api.routers.core.admin_router import _check_admin_access

    app.dependency_overrides[_check_admin_access] = lambda: None
    try:
        assert client.get("/app").status_code == 200
        token = client.cookies.get("pry_csrf")
        assert token
        created = client.post(
            "/app/keys", data={"name": "e2e", "tier": "FREE", "csrf_token": token}
        )
        assert created.status_code == 200
        assert "Key created" in created.text
        key_id = api_keys_service.list_keys()[0]["key_id"]
        revoked = client.post(f"/app/keys/{key_id}/revoke", data={"csrf_token": token})
        assert revoked.status_code == 303
        assert revoked.headers["location"] == "/app"
    finally:
        app.dependency_overrides.pop(_check_admin_access, None)
    assert api_keys_service.list_keys()[0]["is_active"] is False


def test_scrape_returns_documented_shape(client: TestClient) -> None:
    result = {"status": "ok", "content": "# Hello world", "title": "Example", "method": "direct"}
    with patch(SCRAPING) as mock_scraper:
        mock_scraper.scrape = AsyncMock(return_value=result)
        response = client.post("/v1/scrape", json={"url": "https://example.com"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["data"]["markdown"] == "# Hello world"
    assert body["data"]["metadata"]["url"] == "https://example.com"


def test_scrape_without_payment_returns_402() -> None:
    with TestClient(app) as unpaid:
        response = unpaid.post("/v1/scrape", json={"url": "https://example.com"})
    assert response.status_code == 402


def test_crawl_job_reaches_terminal_state(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("pry.core.jobqueue.JobQueue._get_redis", AsyncMock(return_value=None))
    monkeypatch.setattr("pry.core.jobqueue.JobQueue._fire_webhook", AsyncMock())
    pages = [{"status": "ok", "url": "https://example.com", "content": "hello"}]
    payload = {
        "url": "https://example.com",
        "maxPages": 1,
        "maxDepth": 1,
        "webhook": "https://example.com/hook",
    }
    with patch(SCRAPING) as mock_scraper:
        mock_scraper.crawl = AsyncMock(return_value=pages)
        response = client.post("/v1/crawl", json=payload)
    assert response.status_code == 200, response.text
    job_id = response.json()["data"]["id"]
    terminal = None
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        job = client.get(f"/v1/job/{job_id}").json()["data"]
        if job["status"] in ("completed", "failed"):
            terminal = job
            break
        time.sleep(0.01)
    assert terminal is not None, "crawl job never reached a terminal state"
    assert terminal["status"] == "completed"
    assert terminal["result"]["pages"] == pages


def test_actor_run_and_unknown_actor_404(client: TestClient, monkeypatch, tmp_path) -> None:
    import pry.commerce.actor_marketplace as marketplace
    from actor_factory.presets import ALL_PRESETS

    monkeypatch.setattr(marketplace, "ACTOR_DIR", tmp_path)
    preset = next(name for name, spec in sorted(ALL_PRESETS.items()) if spec.processor)
    scrape = AsyncMock(return_value={"status": "ok", "content": "hello world"})
    with patch("pry.commerce.actor_marketplace._scraper.scrape", scrape):
        response = client.post(f"/v1/actors/{preset}/run", json={"url": "https://example.com"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["data"]["content"] == "hello world"
    missing = client.post("/v1/actors/does-not-exist-xyz/run", json={"url": "https://example.com"})
    assert missing.status_code == 404


def test_templates_expose_all_prebuilt_routes(client: TestClient) -> None:
    from pry.commerce.template_engine import list_templates

    assert len(list_templates()) == 110
    response = client.get("/v1/templates")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 110
    assert len(data["templates"]) == 110


@pytest.mark.asyncio
async def test_monitor_tick_creates_exactly_one_run() -> None:
    from pry.actors import scheduler
    from pry.actors.monitor import create_monitor
    from pry.core.db import Monitor, MonitorRun, session_scope

    monitor = await create_monitor("e2e", "https://example.com/feed", schedule_cron="* * * * *")
    with session_scope() as session:
        row = session.query(Monitor).filter(Monitor.monitor_id == monitor["id"]).first()
        row.last_run_at = datetime.now(UTC) - timedelta(hours=2)
    scrape = AsyncMock(return_value={"content": "fresh content"})
    with (
        patch("pry.actors.scheduler._scraper.scrape", scrape),
        patch("pry.actors.monitor.claim_monitor", AsyncMock(return_value="local:test")),
        patch("pry.actors.monitor.release_monitor", AsyncMock()),
    ):
        result = await scheduler.tick(timeout_s=5)
    assert result["due"] == 1
    assert scrape.await_count == 1
    with session_scope() as session:
        runs = session.query(MonitorRun).filter(MonitorRun.monitor_id == monitor["id"]).all()
    assert len(runs) == 1


def test_mcp_surface_counts_and_invalid_arguments() -> None:
    from pry_mcp import make_fallback_server, register_all

    server = make_fallback_server()
    register_all(server)
    listed = asyncio.run(server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
    assert len(listed["result"]["tools"]) == 99
    called = asyncio.run(
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "pry_places_search", "arguments": {}},
            }
        )
    )
    assert called["result"]["isError"] is True
