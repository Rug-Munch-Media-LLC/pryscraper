# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Tests for the Phase 1 server-rendered app UI (keys + usage)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import pry.core.api_keys_service as svc

if TYPE_CHECKING:
    from pathlib import Path

KEY_RE = re.compile(r"pry_[0-9a-f]{8}_[0-9a-f]{32}")


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite DB (same reset pattern as test_api_keys_billing)."""
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


@pytest.fixture
def client(db) -> TestClient:
    from pry.api.routers.core.app_ui import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _csrf(client: TestClient) -> str:
    client.get("/app")
    token = client.cookies.get("pry_csrf")
    assert token
    return token


def test_app_unauthenticated_returns_403(client, monkeypatch) -> None:
    import pry.api.routers.core.admin as admin_mod

    monkeypatch.setattr(admin_mod, "ADMIN_LOOPBACK_ONLY", False)
    response = client.get("/app")
    assert response.status_code == 403


def test_key_label_is_html_escaped(client) -> None:
    svc.issue_key(name="<script>alert(1)</script>", tier="FREE")
    response = client.get("/app")
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_post_without_csrf_is_forbidden(client) -> None:
    response = client.post("/app/keys", data={"name": "no-csrf", "tier": "FREE"})
    assert response.status_code == 403


def test_create_returns_key_exactly_once(client) -> None:
    token = _csrf(client)
    created = client.post(
        "/app/keys",
        data={"csrf_token": token, "name": "phase1", "tier": "FREE"},
    )
    assert created.status_code == 200
    match = KEY_RE.search(created.text)
    assert match, "plaintext key missing from the create response"
    plaintext = match.group(0)
    assert created.text.count(plaintext) == 1
    assert "only time" in created.text

    again = client.get("/app")
    assert plaintext not in again.text


def test_usage_page_renders(client) -> None:
    response = client.get("/app/usage")
    assert response.status_code == 200
    assert "Top endpoints" in response.text
