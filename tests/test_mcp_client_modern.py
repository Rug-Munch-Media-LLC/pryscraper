# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""2026-07-28 modern revision: discover -> tools/list -> tools/call.

Pry implements the modern handshake (and remains dual-era): a 2026-07-28-only
client can discover -> list -> call without ever sending ``initialize``, while
legacy clients negotiate 2025-11-25 unchanged (see ``test_mcp_client_legacy``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from pry_mcp import PRY_TOOLS
from pry_mcp.constants import (
    MCP_DISCOVER_METHOD,
    MCP_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION_META_KEY,
    MCP_UNSUPPORTED_VERSION_CODE,
    discover_result,
)
from tests.conformance_support import (  # noqa: F401 - fixtures
    auth_key,
    conformance,
    live_server,
    modern_headers,
    modern_meta,
    rpc,
)

if TYPE_CHECKING:
    from types import ModuleType


def test_modern_discover_payload_matches_the_constant(live_server: Any) -> None:
    """Discovery is public, stateless and exactly the shared constant."""
    url, _ = live_server
    with httpx.Client(timeout=10) as client:
        response = client.post(
            url,
            headers=modern_headers(),
            json=rpc(1, MCP_DISCOVER_METHOD, {"_meta": modern_meta()}),
        )
    assert response.status_code == 200
    assert response.json()["result"] == discover_result()
    assert "mcp-session-id" not in response.headers, "modern discovery is stateless"


def test_discover_ignores_a_stale_legacy_session(live_server: Any) -> None:
    """Discovery is stateless: a stale Mcp-Session-Id is not a 404."""
    url, _ = live_server
    with httpx.Client(timeout=10) as client:
        response = client.post(
            url,
            headers={**modern_headers(), "Mcp-Session-Id": "stale-legacy-session"},
            json=rpc(6, MCP_DISCOVER_METHOD, {"_meta": modern_meta()}),
        )
    assert response.status_code == 200
    assert response.json()["result"] == discover_result()


async def test_modern_session_without_initialize(
    conformance: ModuleType, live_server: Any, auth_key: str
) -> None:
    """A 2026-07-28-only client: discover -> tools/list -> tools/call."""
    url, key = live_server
    assert key == auth_key
    outcome = await conformance.run_modern_session(url, key)

    assert outcome["errors"] == [], outcome
    assert outcome["tool_count"] == len(PRY_TOOLS) == 99
    assert outcome["tools_call"]["http_status"] == 200
    assert outcome["tools_call"]["is_error"] is False


def test_modern_discover_does_not_authorize_tools_call(live_server: Any, auth_key: str) -> None:
    """Discovery is public; execution is not."""
    url, _ = live_server
    with httpx.Client(timeout=10) as client:
        anonymous = client.post(
            url,
            headers=modern_headers(),
            json=rpc(
                2,
                "tools/call",
                {"_meta": modern_meta(), "name": "pry_scrape_methods", "arguments": {}},
            ),
        )
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == -32001


def test_modern_unsupported_version_is_minus_32022(live_server: Any) -> None:
    """An unsupported declared revision is a modern error, not silent service."""
    url, _ = live_server
    with httpx.Client(timeout=10) as client:
        response = client.post(
            url,
            headers={"Accept": "application/json", "MCP-Protocol-Version": "2099-01-01"},
            json=rpc(3, "tools/list", {"_meta": {MCP_PROTOCOL_VERSION_META_KEY: "2099-01-01"}}),
        )
    error = response.json()["error"]
    assert error["code"] == MCP_UNSUPPORTED_VERSION_CODE
    assert error["data"]["requested"] == "2099-01-01"
    assert MCP_PROTOCOL_VERSION in error["data"]["supported"]
