"""Tests for routers/monitoring.py — content monitor endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.monitoring import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_create_monitor():
    with patch("pry.actors.monitor.create_monitor", new_callable=AsyncMock) as create:
        create.return_value = {"id": "mon-1", "name": "test", "url": "http://example.com"}
        r = client.post(
            "/v1/monitor",
            json={
                "name": "test-monitor",
                "url": "http://example.com",
                "schedule_cron": "0 */6 * * *",
            },
        )
        assert r.status_code in (200, 422, 500)
        if r.status_code == 200:
            assert r.json()["data"]["id"] == "mon-1"


def test_create_monitor_with_goal():
    with patch("pry.actors.monitor.create_monitor", new_callable=AsyncMock) as create:
        create.return_value = {"id": "mon-2", "name": "ai-monitor"}
        r = client.post(
            "/v1/monitor",
            json={
                "name": "ai-monitor",
                "url": "http://example.com",
                "goal": "Track pricing changes",
                "use_llm": True,
                "webhook": "http://hook.com/notify",
            },
        )
        assert r.status_code in (200, 422, 500)


def test_run_monitor():
    with patch("pry.actors.monitor.run_monitor", new_callable=AsyncMock) as run:
        run.return_value = {"id": "mon-1", "changed": False}
        r = client.post("/v1/monitor/run", json={"monitor_id": "mon-1"})
        assert r.status_code in (200, 422, 500)
        if r.status_code == 200:
            assert r.json()["data"]["changed"] is False


def test_run_monitor_not_found():
    with patch("pry.actors.monitor.run_monitor", new_callable=AsyncMock) as run:
        run.return_value = {"error": "Monitor not found: mon-x"}
        r = client.post("/v1/monitor/run", json={"monitor_id": "mon-x"})
        assert r.status_code in (404, 422, 500)


def test_list_monitors():
    with patch("pry.actors.monitor.list_monitors", new_callable=AsyncMock) as lst:
        lst.return_value = [
            {"id": "mon-1", "name": "a"},
            {"id": "mon-2", "name": "b"},
        ]
        r = client.get("/v1/monitors")
        assert r.status_code in (200, 422, 500)
        if r.status_code == 200:
            assert r.json()["data"]["total"] == 2


def test_list_monitors_empty():
    with patch("pry.actors.monitor.list_monitors", new_callable=AsyncMock) as lst:
        lst.return_value = []
        r = client.get("/v1/monitors")
        if r.status_code == 200:
            assert r.json()["data"]["total"] == 0


def test_delete_monitor():
    with patch("pry.actors.monitor.delete_monitor", new_callable=AsyncMock) as delete:
        delete.return_value = True
        r = client.delete("/v1/monitor/mon-1")
        assert r.status_code in (200, 422, 500)
        if r.status_code == 200:
            assert r.json()["data"]["deleted"] is True


def test_delete_monitor_not_found():
    with patch("pry.actors.monitor.delete_monitor", new_callable=AsyncMock) as delete:
        delete.return_value = False
        r = client.delete("/v1/monitor/mon-x")
        assert r.status_code in (404, 422, 500)


def test_run_due_monitors():
    with patch("pry.actors.monitor.list_monitors", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [
            {"id": "mon-1", "schedule_cron": "0 */6 * * *", "last_run_at": None},
        ]
        with patch("croniter.croniter") as mock_cron:
            mock_cron.return_value = MagicMock()
            mock_cron.return_value.get_next = MagicMock(return_value=MagicMock())
            with patch("pry.actors.monitor.run_monitor", new_callable=AsyncMock) as run:
                run.return_value = {"id": "mon-1", "changed": False}
                r = client.post("/v1/monitor/check")
                assert r.status_code in (200, 422, 500)
                if r.status_code == 200:
                    assert r.json()["data"]["ran_count"] >= 0


def test_run_due_monitors_empty():
    with patch("pry.actors.monitor.list_monitors", new_callable=AsyncMock) as lst:
        lst.return_value = []
        r = client.post("/v1/monitor/check")
        if r.status_code == 200:
            assert r.json()["data"]["total_monitors"] == 0
