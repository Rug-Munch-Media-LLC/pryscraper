# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Layer 3: Streamable HTTP transport compliance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pry_mcp import PRY_TOOLS

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


class TestTransportCompliance:
    """Streamable HTTP spec compliance for POST / and GET /."""

    def test_post_json_accept_returns_json_rpc(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        assert len(body["result"]["tools"]) == len(PRY_TOOLS)

    def test_post_sse_accept_returns_event_stream(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = resp.text
        assert "event: message" in text
        assert '"jsonrpc":"2.0"' in text or '"jsonrpc": "2.0"' in text
        assert '"result":{}' in text.replace(" ", "") or '"result": {}' in text

    def test_get_without_sse_accept_returns_406(self, mcp_client: TestClient) -> None:
        resp = mcp_client.get("/", headers={"Accept": "application/json"})
        assert resp.status_code == 406

    def test_get_with_sse_accept_opens_stream(self, mcp_client: TestClient) -> None:
        # ``_sse_test_close_after=1`` is the private test hook shared with
        # mcp_sse.py: emit one keepalive and close so the infinite stream can
        # be consumed by ASGITransport-based tests.
        with mcp_client.stream(
            "GET", "/?_sse_test_close_after=1", headers={"Accept": "text/event-stream"}
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = "".join(resp.iter_text())
            assert ": ping" in body

    def test_parse_error_returns_32700(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            content="not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] is None
        assert body["error"]["code"] == -32700

    def test_invalid_request_returns_32600(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post("/", json={"not": "valid json-rpc"})
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32600

    def test_unknown_method_returns_32601(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 9, "method": "no/such/method"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert "no/such/method" in body["error"]["message"]

    def test_notification_returns_202_empty(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        assert resp.status_code == 202
        assert resp.content == b""

    def test_response_cache_control_no_store(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert "no-store" in resp.headers.get("cache-control", "")


class TestSessionLifecycle:
    """Mcp-Session-Id issuance, validation, and termination."""

    def test_initialize_issues_session_id(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert resp.status_code == 200
        session_id = resp.headers.get("mcp-session-id")
        assert session_id, "initialize must issue an Mcp-Session-Id"
        assert resp.json()["result"]["protocolVersion"] == "2026-07-28"

    def test_known_session_accepted(self, mcp_client: TestClient) -> None:
        init = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        session_id = init.headers["mcp-session-id"]
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Mcp-Session-Id": session_id},
        )
        assert resp.status_code == 200
        assert resp.json()["result"] == {}

    def test_unknown_session_returns_404(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Mcp-Session-Id": "deadbeef"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == -32001

    def test_delete_session_then_404(self, mcp_client: TestClient) -> None:
        init = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        session_id = init.headers["mcp-session-id"]
        deleted = mcp_client.delete("/", headers={"Mcp-Session-Id": session_id})
        assert deleted.status_code == 200
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Mcp-Session-Id": session_id},
        )
        assert resp.status_code == 404

    def test_delete_without_session_returns_400(self, mcp_client: TestClient) -> None:
        resp = mcp_client.delete("/")
        assert resp.status_code == 400
