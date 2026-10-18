# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the persistent audit log (audit item #21).

Covers:
- audit_event() writes a queryable AuditEvent row
- best-effort: a broken engine must NOT raise
- the middleware 429 rate-limit path writes an audit row
- revoke_key() writes an api_key_revoked audit row
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, select

from pry.core import api_keys_service
from pry.core.audit import audit_event
from pry.core.db import models as models_mod, session as session_mod
from pry.core.middleware import PryHttpMiddleware


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB (same pattern as test_api_keys_revocation.py)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    # `pry.core.db.session` only forwards reads; the owner is db_engine.
    import pry.core.db.db_engine as db_engine_mod

    monkeypatch.setattr(db_engine_mod, "_engine", None, raising=False)
    monkeypatch.setattr(db_engine_mod, "_SessionLocal", None, raising=False)

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _audit_rows(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            select(models_mod.AuditEvent).order_by(models_mod.AuditEvent.id)
        ).fetchall()
    return rows


def test_audit_event_writes_row(db) -> None:
    audit_event("test_event", actor="key_abc", path="/v1/x", reason="because")
    rows = _audit_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == "test_event"
    assert row.actor == "key_abc"
    assert row.path == "/v1/x"
    assert row.detail["reason"] == "because"
    assert row.created_at is not None


def test_audit_event_never_raises_on_broken_db(db, monkeypatch) -> None:
    """Best-effort contract: engine failure is swallowed, not raised."""

    def _boom():
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(session_mod, "get_session", _boom)
    # Must not raise.
    audit_event("broken_db_event", actor="x", path="/p", k="v")


@pytest.mark.asyncio
async def test_middleware_429_writes_audit_row(db) -> None:
    """Rate-limit rejection path writes a rate_limit_429 audit row."""
    app = AsyncMock()
    mw = PryHttpMiddleware(app)
    sent = []

    async def send(msg):
        sent.append(msg)

    blocked = (False, {"remaining": 0, "retry_after": 1, "reason": "rate_limited"})
    with (
        patch("pry.core.middleware.settings.api_key", ""),
        patch("pry.core.middleware._path_exists", return_value=True),
        patch("pry.core.middleware.ratelimiter") as mock_rl,
    ):
        mock_rl.check.return_value = blocked
        mock_rl.default_rpm = 60
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/scrape",
            "headers": [],
            "client": ["127.0.0.1", 0],
        }
        await mw(scope, None, send)

    assert sent[0]["status"] == 429
    rows = [r for r in _audit_rows(db) if r.event_type == "rate_limit_429"]
    assert len(rows) == 1
    assert rows[0].actor == "127.0.0.1"  # no key -> IP-based actor
    assert rows[0].path == "/v1/scrape"


def test_revoke_key_writes_audit_row(db) -> None:
    issued = api_keys_service.issue_key(name="audit-me")
    key_id = issued["key_id"]
    assert api_keys_service.revoke_key(key_id) is True

    rows = [r for r in _audit_rows(db) if r.event_type == "api_key_revoked"]
    assert len(rows) == 1
    assert rows[0].detail["key_id"] == key_id


def test_revoke_unknown_key_writes_no_audit_row(db) -> None:
    assert api_keys_service.revoke_key("nope") is False
    rows = [r for r in _audit_rows(db) if r.event_type == "api_key_revoked"]
    assert rows == []
