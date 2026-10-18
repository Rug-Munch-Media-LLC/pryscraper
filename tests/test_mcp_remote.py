# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Remote MCP transport — in-process handshake, auth gate, and compose wiring.

These tests exercise the Streamable HTTP surface exactly as a remote client
sees it (TestClient drives the real ASGI app):

* ``initialize`` issues ``Mcp-Session-Id`` and advertises the server;
* ``tools/list`` returns the full registered surface;
* ``tools/call`` is fail-closed (401 anonymous / wrong key) and a valid Bearer
  executes a local tool;
* successful results carry ``structuredContent`` — every tool declares an
  ``outputSchema``, and the official SDK client rejects a response without it;
* ``/health`` reports the shape operators and load balancers probe;
* the shipped compose files define the ``pry-mcp`` service and expose it in
  the self-host profile with the API key re-exported.

The compose assertions use the same real ``docker compose config`` oracle as
``tests/selfhost`` (and skip when the CLI is unavailable).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from pry_mcp import PRY_TOOLS
from pry_mcp.app import create_mcp_app

TOOL_COUNT = len(PRY_TOOLS)
INITIALIZE: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "pytest-remote", "version": "1"},
    },
}
CALL: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {"name": "pry_actor_catalog", "arguments": {"limit": 1}},
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_mcp_app())


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    import pry.core.settings as settings_mod

    key = "remote-mcp-test-key"
    monkeypatch.setattr(settings_mod.settings, "api_key", key, raising=False)
    return key


# ── transport ────────────────────────────────────────────────────────


def test_health_shape(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["server"] == "pry-mcp"
    assert body["tools_count"] == TOOL_COUNT
    assert body["resources_count"] > 0
    assert body["prompts_count"] > 0
    assert "streamable-http" in body["transports"]
    assert body["protocol_version"]


def test_initialize_issues_session_and_lists_tools(client: TestClient) -> None:
    init = client.post("/", json=INITIALIZE)
    assert init.status_code == 200
    assert init.headers.get("mcp-session-id"), "initialize must issue a session id"
    assert init.json()["result"]["serverInfo"]["name"] == "pry"

    listed = client.post("/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed.status_code == 200
    tools = listed.json()["result"]["tools"]
    assert [t["name"] for t in tools] == [t["name"] for t in PRY_TOOLS]
    assert len(tools) == TOOL_COUNT


def test_unknown_session_is_404(client: TestClient) -> None:
    resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
        headers={"mcp-session-id": "does-not-exist"},
    )
    assert resp.status_code == 404


def test_notifications_return_202(client: TestClient) -> None:
    resp = client.post("/", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 202
    assert not resp.content


# ── auth + structured content ────────────────────────────────────────


def test_tools_call_requires_a_key(client: TestClient, api_key: str) -> None:
    anonymous = client.post("/", json=CALL)
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == -32001

    wrong = client.post("/", json=CALL, headers={"authorization": "Bearer nope"})
    assert wrong.status_code == 401


def test_tools_call_with_key_returns_structured_content(client: TestClient, api_key: str) -> None:
    resp = client.post("/", json=CALL, headers={"authorization": f"Bearer {api_key}"})
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result.get("isError") is False
    # Regression: the official SDK client raises
    # "Tool ... has an output schema but did not return structured content"
    # when this key is missing. Every Pry tool declares an outputSchema.
    assert isinstance(result.get("structuredContent"), dict)
    assert result["structuredContent"]["count"] == 1
    assert result["structuredContent"]["total"] >= 1


# ── compose wiring ───────────────────────────────────────────────────


def _assert_mcp_identity(service: dict) -> None:
    assert service["read_only"] is True
    assert service["restart"] == "unless-stopped"
    assert service["init"] is True
    assert service["entrypoint"][:2] == ["uvicorn", "pry_mcp.asgi:app"]


def _assert_mcp_ports(service: dict, published: str) -> None:
    assert {str(p["published"]) for p in service["ports"]} == {published}
    assert all(p["target"] == 8006 for p in service["ports"])


def _assert_mcp_health(service: dict) -> None:
    assert "8006/health" in " ".join(service["healthcheck"]["test"])


def test_base_compose_defines_pry_mcp() -> None:
    from tests.selfhost.conftest import render_compose

    service = render_compose(with_selfhost=False)["services"]["pry-mcp"]
    _assert_mcp_identity(service)
    _assert_mcp_ports(service, "8006")
    _assert_mcp_health(service)
    assert set(service["depends_on"]) == {"pry", "postgres", "redis"}
    env = service["environment"]
    assert env["PRY_API_URL"] == "http://pry:8002"
    assert env["PRY_REDIS_URL"].startswith("redis://")
    assert env["PRY_PORT"] == "8006"

def test_selfhost_exposes_remote_mcp_by_default() -> None:
    from tests.selfhost.conftest import render_compose

    model = render_compose()
    assert "pry-mcp" in model["services"], "self-hosters must get the remote MCP"
    service = model["services"]["pry-mcp"]

    assert {str(p["published"]) for p in service["ports"]} == {"8006"}
    env = service["environment"]
    # --env-file only supplies interpolation; the key must be re-exported or
    # every tools/call through the published port is 401 in prod.
    assert "PRY_API_KEY" in env
    assert env["PRY_API_URL"] == "http://pry:8002"
    assert env["PRY_REDIS_URL"] == ""
    assert set(service["depends_on"]) == {"pry"}
