"""Dark-path coverage for src/pry/core/middleware.py (audit win B9).

Targets the sections the audit flagged: auth helpers, the master-key
admin identity binding, DB-key authentication incl. store-outage
fail-closed behavior, usage flush persistence/failure, the ASGI route
table walk, and the rate-limit-blocked response path.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from pry.core import middleware as mw

if TYPE_CHECKING:
    import pytest
from pry.core.middleware import PryHttpMiddleware, _flush_usage, _route_table_root


def _scope(bearer: str = "", host: str = "10.0.0.1") -> dict:
    headers = []
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return {"type": "http", "headers": headers, "client": (host, 1234), "path": "/v1/x"}


# ── Master-key admin identity binding ────────────────────────────────────


def test_master_key_binds_admin_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mw.settings, "api_key", "master-secret", raising=False)
    scope = _scope("master-secret")
    assert mw.request_authorized(scope) is True
    record = scope["pry_api_key"]
    assert record["key_id"] == "legacy-master"
    assert "admin" in record["scopes"]
    assert record["tier"] == "ENTERPRISE"


def test_master_key_wrong_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mw.settings, "api_key", "master-secret", raising=False)
    scope = _scope("not-the-key")
    assert mw.request_authorized(scope) is False
    assert "pry_api_key" not in scope


def test_db_key_binds_record_into_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mw.settings, "api_key", "", raising=False)
    record = {"key_id": "key_abc", "user_id": "u1", "scopes": ["scrape"]}
    with patch("pry.api.api_keys_service.authenticate", return_value=record):
        scope = _scope("pry_live_good")
        assert mw.request_authorized(scope) is True
    assert scope["pry_api_key"] == record


def test_db_key_store_outage_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth-store exception must reject, never 500 or fail open."""
    monkeypatch.setattr(mw.settings, "api_key", "", raising=False)

    def boom(token):
        raise RuntimeError("db down")

    with patch("pry.api.api_keys_service.authenticate", side_effect=boom):
        scope = _scope("pry_live_whatever")
        assert mw.request_authorized(scope) is False
    assert "pry_api_key" not in scope


def test_db_key_unknown_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mw.settings, "api_key", "", raising=False)
    with patch("pry.api.api_keys_service.authenticate", return_value=None):
        assert mw.request_authorized(_scope("pry_live_unknown")) is False


# ── Usage flush ──────────────────────────────────────────────────────────


def test_flush_usage_empty_queue_is_zero() -> None:
    mw._usage_queue.clear()
    assert _flush_usage() == 0


def test_flush_usage_persists_batch_and_clears() -> None:
    mw._usage_queue.clear()
    mw._usage_queue.append({"key_id": "k1", "operation": "/v1/scrape", "status": "success"})
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    with (
        patch("pry.core.db.session.get_session", return_value=ctx),
        patch("pry.core.db.models.Usage", MagicMock()),
    ):
        written = _flush_usage()
    assert written == 1
    assert session.add.called
    assert session.commit.called
    assert mw._usage_queue == []


def test_flush_usage_db_failure_drops_batch_returns_zero() -> None:
    mw._usage_queue.clear()
    mw._usage_queue.append({"key_id": "k2", "operation": "/v1/x", "status": "error"})
    ctx = MagicMock()
    ctx.__enter__.side_effect = RuntimeError("no db")
    with patch("pry.core.db.session.get_session", return_value=ctx):
        assert _flush_usage() == 0
    # queue was drained either way — metering must never back up serving
    assert mw._usage_queue == []


# ── Route table walk ─────────────────────────────────────────────────────


def test_route_table_root_none_app() -> None:
    assert _route_table_root(None) is None


def test_route_table_root_direct_hit() -> None:
    app = SimpleNamespace(routes=[object()])
    assert _route_table_root(app) is app


def test_route_table_root_walks_chain() -> None:
    leaf = SimpleNamespace(routes=[object()])
    mid = SimpleNamespace(app=leaf)
    outer = SimpleNamespace(app=mid)
    assert _route_table_root(outer) is leaf


def test_route_table_root_gives_up_after_depth() -> None:
    a: dict = {}
    b: dict = {}
    a["app"] = b
    b["app"] = a  # cycle — must terminate via depth cap
    assert _route_table_root(a) is None


# ── Rate-limit blocked response path (ASGI-level) ────────────────────────


def test_rate_limit_blocked_emits_429_with_headers() -> None:
    """When the limiter refuses, the middleware answers 429 + retry_after."""
    stats = {
        "limit": 5,
        "remaining": 0,
        "quota_reset_at": 9999999999,
        "quota_used": 5,
        "quota_limit": 10000,
        "retry_after": 3,
        "reason": "rate_limited",
    }
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    async def app(scope, receive, send):  # pragma: no cover - must not run
        raise AssertionError("downstream must not see blocked requests")

    # Route table must know the path, else the unknown-path pass-through
    # returns before rate limiting ever runs. Must be REAL Starlette
    # routes — the matcher isinstance-checks them.
    from starlette.routing import Route

    async def _endpoint():  # pragma: no cover - never invoked
        return {}

    app.routes = [Route("/v1/scrape", _endpoint)]
    mw_inst = PryHttpMiddleware(app=app)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/scrape",
        "headers": [(b"authorization", b"Bearer dbkey1234567890")],
        "client": ("203.0.113.9", 5),
        "query_string": b"",
    }
    with (
        patch.object(mw, "request_authorized", return_value=True),
        patch.object(mw, "user_ratelimiter") as rl,
    ):
        rl.check.return_value = (False, stats)
        asyncio.run(mw_inst.__call__(scope, receive, send))

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 429
    hdrs = dict(sent[0]["headers"])
    assert hdrs[b"x-ratelimit-remaining"] == b"0"
    assert hdrs[b"x-request-id"]
    body = json.loads(sent[1]["body"])
    assert body["code"] == "rate_limit_exceeded"
