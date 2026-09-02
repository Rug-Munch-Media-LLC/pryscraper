# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for API-key revocation (audit item #6).

Covers:
- issue -> authenticate OK -> revoke -> authenticate REJECTED (fail closed)
- revoke unknown key returns False / admin endpoint 404
- admin surface DELETE /v1/admin/keys/{key_id} revokes and 404s unknown keys
- already-revoked key cannot be revoked twice (returns False)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app
from pry.api.routers.core.admin import ADMIN_PREFIX
from pry.core import api_keys_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB (same pattern as test_hosting.py)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)

    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


# ── Service-level: fail-closed revocation ───────────────────────────────────


def test_revoke_rejects_authentication(db) -> None:
    """issue -> authenticate OK -> revoke -> authenticate REJECTED."""
    issued = api_keys_service.issue_key(name="revoke-me")
    plaintext = issued["plaintext"]
    key_id = issued["key_id"]

    # Before revocation the key authenticates.
    record = api_keys_service.authenticate(plaintext)
    assert record is not None
    assert record["key_id"] == key_id

    assert api_keys_service.revoke_key(key_id) is True

    # Fail closed: revoked key must not authenticate.
    assert api_keys_service.authenticate(plaintext) is None


def test_revoke_unknown_key_returns_false(db) -> None:
    assert api_keys_service.revoke_key("key_does_not_exist") is False


def test_revoke_twice_returns_false(db) -> None:
    issued = api_keys_service.issue_key()
    assert api_keys_service.revoke_key(issued["key_id"]) is True
    # Already revoked (is_active=False) — second revoke is a no-op.
    assert api_keys_service.revoke_key(issued["key_id"]) is False


def test_revoked_key_still_listed_as_inactive(db) -> None:
    issued = api_keys_service.issue_key()
    api_keys_service.revoke_key(issued["key_id"])
    keys = {k["key_id"]: k for k in api_keys_service.list_keys()}
    assert keys[issued["key_id"]]["is_active"] is False


# ── Admin surface: DELETE /v1/admin/keys/{key_id} ───────────────────────────


@pytest.fixture
def client(db) -> TestClient:
    # Loopback peer so the admin router's loopback-only gate passes
    # (same approach as tests/test_router_admin.py).
    return TestClient(app, client=("127.0.0.1", 51234))


def test_admin_revoke_endpoint(client, db) -> None:
    issued = api_keys_service.issue_key()
    plaintext = issued["plaintext"]
    key_id = issued["key_id"]
    assert api_keys_service.authenticate(plaintext) is not None

    resp = client.delete(f"{ADMIN_PREFIX}/v1/admin/keys/{key_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["revoked"] is True
    assert body["key_id"] == key_id

    # Fail closed after revocation.
    assert api_keys_service.authenticate(plaintext) is None


def test_admin_revoke_unknown_key_404(client, db) -> None:
    resp = client.delete(f"{ADMIN_PREFIX}/v1/admin/keys/key_unknown")
    assert resp.status_code == 404


# ── Admin RBAC in remote mode (audit item #5) ───────────────────────────────


def test_remote_admin_requires_admin_role(tmp_path, monkeypatch):
    """PRY_ADMIN_LOOPBACK_ONLY=false + non-ADMIN user's key → 403 fail closed.

    Regression: with loopback-only disabled, ANY valid API key could reach
    the admin surface. Remote mode now requires the key's owner to hold the
    ADMIN role in the users table.
    """
    from fastapi import HTTPException
    from sqlalchemy import create_engine

    import pry.api.routers.core.admin as admin_mod
    import pry.core.api_keys_service as aks
    import pry.core.db.models as models
    from pry.api.routers.core.admin import _check_admin_access

    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/rbac.db")
    # ADMIN_LOOPBACK_ONLY is read at import time — patch the module constant.
    monkeypatch.setattr(admin_mod, "ADMIN_LOOPBACK_ONLY", False)
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)
    engine = create_engine(f"sqlite:///{tmp_path}/rbac.db")
    models.Base.metadata.create_all(engine)

    # Non-loopback client with NO key → 403
    req = type("R", (), {"client": type("C", (), {"host": "10.1.2.3"})(), "headers": {}})()
    with pytest.raises(HTTPException) as exc:
        _check_admin_access(req)  # type: ignore[arg-type]
    assert exc.value.status_code == 403

    # Valid key owned by a NON-admin user → 403
    from pry.core.db.session import get_session

    with get_session() as session:
        session.add(models.User(user_id="u_nonadmin", email="na@x.io", password_hash="x"))
        session.commit()
    issued = aks.issue_key(user_id="u_nonadmin", name="t")
    key = issued["plaintext"] if isinstance(issued, dict) and "plaintext" in issued else str(issued)

    class _Req:
        def __init__(self) -> None:
            self.client = type("C", (), {"host": "10.1.2.3"})()
            self.headers = {"authorization": f"Bearer {key}"}

    with pytest.raises(HTTPException) as exc2:
        _check_admin_access(_Req())
    assert "ADMIN role" in exc2.value.detail
    engine.dispose()
