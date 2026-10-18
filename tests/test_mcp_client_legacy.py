# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Legacy revision policy: what an ``initialize`` client negotiates.

Revision policy under test (``pry_mcp/constants.py``):

* a supported requested revision is echoed back verbatim;
* an unknown revision gets the server ceiling (``MCP_PROTOCOL_VERSION``);
* every revision — supported or not — exposes exactly the same 99 tools and
  never produces a JSON-RPC error or a 5xx.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from pry_mcp import PRY_TOOLS
from pry_mcp.constants import (
    MCP_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    negotiate_protocol_version,
)
from tests.conformance_support import (  # noqa: F401 - fixtures
    UNKNOWN_REVISIONS,
    conformance,
    live_server,
    rpc,
)

if TYPE_CHECKING:
    from types import ModuleType


async def test_revision_matrix(conformance: ModuleType, live_server: Any) -> None:
    url, _ = live_server
    matrix = await conformance.run_wire_matrix(url, 30, extra_versions=("not-a-revision",))

    assert matrix["errors"] == []
    assert {row["requested"] for row in matrix["rows"]} == {
        *SUPPORTED_PROTOCOL_VERSIONS,
        conformance.UNKNOWN_VERSION,
        "not-a-revision",
    }

    for row in matrix["rows"]:
        requested = row["requested"]
        expected = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        assert row["negotiated"] == expected, row
        assert row["negotiated"] == negotiate_protocol_version(requested)
        assert row["tools"] == len(PRY_TOOLS) == 99, row
        assert row["http_status"] == 200, row
        assert row["session_id"] is True, row


async def test_unknown_revision_returns_ceiling_not_an_error(
    conformance: ModuleType, live_server: Any
) -> None:
    url, _ = live_server
    matrix = await conformance.run_wire_matrix(url, 30, extra_versions=("not-a-revision",))
    unknown_rows = [row for row in matrix["rows"] if row["requested"] in UNKNOWN_REVISIONS]
    assert len(unknown_rows) == len(UNKNOWN_REVISIONS)
    for row in unknown_rows:
        assert row["negotiated"] == MCP_PROTOCOL_VERSION
        assert "error" not in row, row


def test_legacy_initialize_still_negotiates_2025_11_25(live_server: Any) -> None:
    """The legacy handshake is unchanged by the modern addition."""
    url, _ = live_server
    with httpx.Client(timeout=10) as client:
        response = client.post(
            url,
            headers={"Accept": "application/json"},
            json=rpc(
                4,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest-legacy", "version": "1"},
                },
            ),
        )
    result = response.json()["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert result["serverInfo"]["name"] == "pry"
    assert response.headers.get("mcp-session-id")


def test_unknown_method_is_still_minus_32601(live_server: Any) -> None:
    url, _ = live_server
    with httpx.Client(timeout=10) as client:
        response = client.post(
            url, headers={"Accept": "application/json"}, json=rpc(5, "does/not/exist")
        )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32601
