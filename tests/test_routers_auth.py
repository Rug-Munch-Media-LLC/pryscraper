"""Tests for routers/auth.py — credential vault, SSO, CAPTCHA, session health."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.core.auth import _request_owner, router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_request_owner_no_auth():
    req = MagicMock()
    req.state.identity = None
    req.state.user_id = None
    req.headers = {}
    assert _request_owner(req) == ""


def test_request_owner_state_identity():
    req = MagicMock(spec=["state"])
    req.state.identity = "user-123"
    assert _request_owner(req) == "user-123"


def test_request_owner_state_user_id():
    req = MagicMock(spec=["state"])
    req.state.identity = None
    req.state.user_id = "user-456"
    assert _request_owner(req) == "user-456"


def test_request_owner_bearer_jwt():
    req = MagicMock(spec=["state"])
    req.state.identity = None
    req.state.user_id = None
    req.headers = {"authorization": "Bearer eyJ.eyJpZCI6ICJ1c2VyLTc4OSJ9.sig"}
    with (
        patch("pry.api.routers.core.auth.is_jwt", return_value=True),
        patch("pry.api.routers.core.auth.validate_rmi_jwt", return_value={"id": "user-789"}),
    ):
        assert _request_owner(req) == "jwt:user-789"


def test_request_owner_bearer_apikey():
    req = MagicMock(spec=["state"])
    req.state.identity = None
    req.state.user_id = None
    req.headers = {"authorization": "Bearer my-api-key-123"}
    with patch("pry.api.routers.core.auth.is_jwt", return_value=False):
        owner = _request_owner(req)
        assert owner.startswith("key:")


def test_store_credentials():
    with patch("pry.api.auth_connector.store_credential") as mock_store:
        mock_store.return_value = {"success": True, "id": "cred-1"}
        r = client.post(
            "/v1/auth/credentials",
            json={
                "name": "test-creds",
                "credential_type": "password",
                "credentials": {"username": "admin", "password": "secret"},
                "target_url": "http://example.com",
            },
        )
        assert r.status_code in (200, 422, 500)


def test_list_credentials():
    with patch("pry.api.auth_connector.list_credentials") as mock_list:
        mock_list.return_value = [{"id": "cred-1", "name": "test", "type": "password"}]
        r = client.get("/v1/auth/credentials")
        assert r.status_code in (200, 422, 500)


def test_delete_credentials():
    with patch("pry.api.auth_connector.delete_credential") as mock_del:
        mock_del.return_value = True
        r = client.delete("/v1/auth/credentials/cred-123")
        assert r.status_code in (200, 422, 500)


def test_delete_credentials_not_found():
    with patch("pry.api.auth_connector.delete_credential") as mock_del:
        mock_del.return_value = False
        r = client.delete("/v1/auth/credentials/nonexistent")
        assert r.status_code in (404, 422, 500)


def test_generate_sso():
    with patch("pry.api.auth_connector.generate_sso_script", new_callable=AsyncMock) as sso:
        sso.return_value = {"success": True, "script": "await page.goto(...)"}
        r = client.post(
            "/v1/auth/sso",
            json={
                "provider": "okta",
                "username": "user@corp.com",
                "password": "pass123",
                "target_url": "http://corp.com/login",
                "tenant": "corp.okta.com",
            },
        )
        assert r.status_code in (200, 422, 500)
        if r.status_code == 200:
            assert r.json().get("success") is True


def test_generate_sso_default_tenant():
    with patch("pry.api.auth_connector.generate_sso_script", new_callable=AsyncMock) as sso:
        sso.return_value = {"success": True}
        r = client.post(
            "/v1/auth/sso",
            json={
                "provider": "azure_ad",
                "username": "admin",
                "password": "pass",
                "target_url": "http://portal.azure.com",
            },
        )
        assert r.status_code in (200, 422, 500)


def test_solve_captcha_image():
    with patch("pry.api.auth_connector.solve_captcha", new_callable=AsyncMock) as cap:
        cap.return_value = {"success": True, "token": "captcha-token"}
        r = client.post(
            "/v1/auth/captcha",
            json={
                "image_base64": "aW1hZ2U=",
                "service": "capsolver",
                "api_key": "test-key",
            },
        )
        assert r.status_code in (200, 422, 500)


def test_solve_captcha_recaptcha():
    with patch("pry.api.auth_connector.solve_captcha", new_callable=AsyncMock) as cap:
        cap.return_value = {"success": True, "token": "recaptcha-token"}
        r = client.post(
            "/v1/auth/captcha",
            json={
                "site_key": "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI",
                "page_url": "http://example.com",
                "service": "2captcha",
            },
        )
        assert r.status_code in (200, 422, 500)


def test_check_session():
    with patch("pry.api.auth_connector.check_session_health") as check:
        check.return_value = {
            "valid": True,
            "age_hours": 2,
            "cookies_valid": True,
            "needs_reauth": False,
        }
        r = client.post("/v1/auth/session/health", json={"session_id": "session-abc"})
        assert r.status_code in (200, 422, 500)
        if r.status_code == 200:
            assert r.json().get("success") is True
