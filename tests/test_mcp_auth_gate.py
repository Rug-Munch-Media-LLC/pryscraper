# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the MCP SSE auth gate on ``tools/call``.

The security audit found that ``tools/call`` on the legacy SSE transport
executes arbitrary code. A gate was added to ``mcp_post_message`` (matching
the Streamable HTTP transport in ``pry_mcp/app.py``): ``tools/call`` requires
a valid credential, while discovery methods (``tools/list``,
``resources/list``, etc.) stay public so agents can enumerate the surface
without a key.

These tests exercise the FULL HTTP path through the mounted ``/mcp`` sub-app
using the conftest ``client`` fixture. The JSON-RPC response is delivered on
the session's SSE outbound queue (``mcp_post_message`` returns HTTP 202 and
enqueues the response), so we assert on the enqueued event.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from pry.api.mcp_sse import MCP_SSE_SESSIONS, MCP_SSE_TASKS

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

# A non-empty API key forces request_authorized to require a valid Bearer
# credential (with an empty key, TestClient is treated as loopback and the
# gate never fires). We set it per-test and restore it afterwards.
_TEST_API_KEY = "test-mcp-auth-key"


@pytest.fixture(autouse=True)
def _mcp_auth_gate_cleanup():
    """Drain SSE-global state after every test in this module."""
    yield
    MCP_SSE_SESSIONS.clear()
    MCP_SSE_TASKS.clear()


@pytest.fixture(autouse=True)
def _force_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a non-empty API key so the auth gate is actually enforced."""
    import pry.core.settings as _settings_mod

    monkeypatch.setattr(_settings_mod.settings, "api_key", _TEST_API_KEY)


def _new_session(session_id: str) -> asyncio.Queue[str]:
    """Register a session queue and return it."""
    q: asyncio.Queue[str] = asyncio.Queue()
    MCP_SSE_SESSIONS[session_id] = q
    return q


def _post_message(
    client: TestClient, session_id: str, body: dict, headers: dict | None = None
) -> tuple[int, list[dict]]:
    """POST a JSON-RPC message and return (http_status, parsed enqueued events)."""
    resp = client.post(
        f"/mcp/messages/{session_id}",
        json=body,
        headers=headers or {},
    )
    q = MCP_SSE_SESSIONS.get(session_id)
    events: list[dict] = []
    if q is not None:
        while not q.empty():
            raw = q.get_nowait()
            # SSE event format: "event: message\ndata: {json}\n\n"
            data_line = next((ln for ln in raw.splitlines() if ln.startswith("data: ")), "")
            if data_line:
                events.append(json.loads(data_line[6:]))
    return resp.status_code, events


# ── Unauthenticated tools/call → -32001 ───────────────────────────────


def test_unauthenticated_tools_call_is_rejected(client: TestClient) -> None:
    """tools/call without a credential is gated with a -32001 error."""
    _new_session("sid_unauth")
    status, events = _post_message(
        client,
        "sid_unauth",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "pry_scrape", "arguments": {"url": "https://example.com"}},
        },
    )
    # mcp_post_message always returns 202; the error rides the SSE stream.
    assert status == 202
    assert len(events) == 1
    err = events[0]["error"]
    assert err["code"] == -32001
    assert "requires an API key" in err["message"]
    assert events[0]["id"] == 1


def test_unauthenticated_tools_call_does_not_execute(client: TestClient) -> None:
    """The gated tools/call must NOT produce a result (only the auth error)."""
    _new_session("sid_unauth_noexec")
    _, events = _post_message(
        client,
        "sid_unauth_noexec",
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "pry_scrape", "arguments": {"url": "https://example.com"}},
        },
    )
    assert len(events) == 1
    assert "result" not in events[0]
    assert events[0]["error"]["code"] == -32001


# ── Authenticated tools/call → succeeds ───────────────────────────────


def test_authenticated_tools_call_succeeds(client: TestClient) -> None:
    """tools/call with a valid Bearer key passes the gate and executes."""
    _new_session("sid_auth")
    status, events = _post_message(
        client,
        "sid_auth",
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "pry_scrape", "arguments": {"url": "https://example.com"}},
        },
        headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
    )
    assert status == 202
    assert len(events) == 1
    # The gate did not fire: we get a result, not a -32001 auth error.
    assert "error" not in events[0] or events[0]["error"]["code"] != -32001
    assert "result" in events[0]
    assert events[0]["id"] == 2


def test_authenticated_tools_call_returns_result(client: TestClient) -> None:
    """Authenticated tools/call yields a tool result payload."""
    _new_session("sid_auth_result")
    _, events = _post_message(
        client,
        "sid_auth_result",
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "pry_scrape", "arguments": {"url": "https://example.com"}},
        },
        headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
    )
    assert len(events) == 1
    result = events[0].get("result", {})
    assert "content" in result


# ── Discovery methods stay public ─────────────────────────────────────


def test_tools_list_without_auth_succeeds(client: TestClient) -> None:
    """tools/list is public by design — no credential required."""
    _new_session("sid_list")
    status, events = _post_message(
        client,
        "sid_list",
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
    )
    assert status == 202
    assert len(events) == 1
    assert "error" not in events[0]
    assert "result" in events[0]
    assert "tools" in events[0]["result"]


def test_resources_list_without_auth_succeeds(client: TestClient) -> None:
    """resources/list is public by design — no credential required."""
    _new_session("sid_resources")
    status, events = _post_message(
        client,
        "sid_resources",
        {"jsonrpc": "2.0", "id": 4, "method": "resources/list", "params": {}},
    )
    assert status == 202
    assert len(events) == 1
    assert "error" not in events[0]
    assert "result" in events[0]


def test_initialize_without_auth_succeeds(client: TestClient) -> None:
    """initialize is public by design — no credential required."""
    _new_session("sid_init")
    status, events = _post_message(
        client,
        "sid_init",
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert status == 202
    assert len(events) == 1
    assert "error" not in events[0]
    assert "result" in events[0]
