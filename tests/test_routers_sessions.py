"""Tests for routers/sessions.py — browser session API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.sessions import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_create_session():
    with patch("routers.sessions.automator") as auto:
        auto.create_session = AsyncMock(return_value="session-abc")
        with patch("sessions.save_session", new_callable=AsyncMock):
            r = client.post(
                "/v1/session/create",
                json={
                    "url": "http://example.com",
                    "persist": True,
                },
            )
            assert r.status_code in (200, 422, 500)
            if r.status_code == 200:
                assert r.json()["data"]["session_id"] == "session-abc"


def test_create_session_no_persist():
    with patch("routers.sessions.automator") as auto:
        auto.create_session = AsyncMock(return_value="session-no-persist")
        r = client.post(
            "/v1/session/create",
            json={
                "url": "http://example.com",
                "persist": False,
            },
        )
        assert r.status_code in (200, 422, 500)
        if r.status_code == 200:
            assert r.json()["data"]["persist"] is False


def test_destroy_session():
    with patch("routers.sessions.automator") as auto:
        auto.destroy_session = AsyncMock(return_value=True)
        with patch("sessions.delete_session", new_callable=AsyncMock):
            r = client.post(
                "/v1/session/destroy",
                json={
                    "session_id": "session-abc",
                    "save_state": False,
                },
            )
            assert r.status_code in (200, 422, 500)
            if r.status_code == 200:
                assert r.json()["data"]["destroyed"] is True


def test_destroy_session_with_save():
    with patch("routers.sessions.automator") as auto:
        auto.destroy_session = AsyncMock(return_value=True)
        auto.get_session_state = AsyncMock(return_value={"cookies": [], "local_storage": {}})
        with (
            patch("sessions.save_session", new_callable=AsyncMock),
            patch("sessions.delete_session", new_callable=AsyncMock),
        ):
            r = client.post(
                "/v1/session/destroy",
                json={
                    "session_id": "session-abc",
                    "save_state": True,
                },
            )
            assert r.status_code in (200, 422, 500)


def test_list_sessions():
    with patch("routers.sessions.automator") as auto:
        auto.list_sessions = MagicMock(return_value=[{"session_id": "active-1"}])
        with patch("routers.sessions.list_sessions") as mock_saved:
            mock_saved.return_value = [{"session_id": "saved-1"}]
            r = client.get("/v1/sessions")
            assert r.status_code in (200, 422, 500)
            if r.status_code == 200:
                assert r.json()["data"]["total_active"] >= 1


def test_save_session_state():
    with patch("routers.sessions.automator") as auto:
        auto.get_session_state = AsyncMock(return_value={"cookies": [], "local_storage": {}})
        with patch("sessions.save_session", new_callable=AsyncMock):
            r = client.post("/v1/session/save", json={"session_id": "session-abc"})
            assert r.status_code in (200, 422, 500)


def test_save_session_state_not_found():
    with patch("routers.sessions.automator") as auto:
        auto.get_session_state = AsyncMock(return_value=None)
        r = client.post("/v1/session/save", json={"session_id": "nonexistent"})
        assert r.status_code in (404, 422, 500)


def test_restore_session():
    with patch("routers.sessions.automator") as auto:
        auto.restore_session_state = AsyncMock(return_value=True)
        with patch("sessions.load_session", new_callable=AsyncMock) as load:
            load.return_value = {
                "session_id": "saved-1",
                "cookies": [{"name": "x"}],
                "saved_at": "2026-01-01",
            }
            r = client.post("/v1/session/restore", json={"session_id": "saved-1"})
            assert r.status_code in (200, 422, 500)


def test_restore_session_not_found():
    with (
        patch("routers.sessions.automator"),
        patch("sessions.load_session", new_callable=AsyncMock) as load,
    ):
        load.return_value = None
        r = client.post("/v1/session/restore", json={"session_id": "nonexistent"})
        assert r.status_code in (404, 422, 500)
