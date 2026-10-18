# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Client conformance: what an official MCP client actually gets from Pry.

Every check runs against a real uvicorn server on a loopback port, because the
official SDK's Streamable HTTP transport is not exercised by ``TestClient``.

Revision policy under test (``pry_mcp/constants.py``):

* a supported requested revision is echoed back verbatim;
* an unknown revision gets the server ceiling (``MCP_PROTOCOL_VERSION``);
* every revision — supported or not — exposes exactly the same 99 tools and
  never produces a JSON-RPC error or a 5xx.

SDK facts recorded here (official ``mcp`` 2.2.0):

* ``ClientSession.initialize()`` always requests ``LATEST_HANDSHAKE_VERSION``
  (2025-11-25). It has no per-call version argument, so the per-revision
  matrix is driven with raw ``initialize`` requests — an SDK limitation, not a
  server limitation.
* 2026-07-28 is a *modern* revision reached through ``server/discover``, not
  ``initialize``. Pry implements the modern handshake (and remains dual-era):
  a 2026-07-28-only client can discover -> list -> call without ever sending
  ``initialize``, while legacy clients negotiate 2025-11-25 unchanged.
"""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from pry_mcp import PRY_PROMPTS, PRY_RESOURCES, PRY_TOOLS

if TYPE_CHECKING:
    from types import ModuleType

from pry_mcp.constants import (
    MCP_DISCOVER_METHOD,
    MCP_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION_META_KEY,
    MCP_UNSUPPORTED_VERSION_CODE,
    SUPPORTED_PROTOCOL_VERSIONS,
    discover_result,
    negotiate_protocol_version,
)

REPO = Path(__file__).resolve().parents[1]
API_KEY = "mcp-conformance-key"
UNKNOWN_REVISIONS = ("1999-01-01", "not-a-revision")


# ── fixtures ─────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def conformance() -> ModuleType:
    """Load the shipped runner so the test proves the script as well."""
    spec = importlib.util.spec_from_file_location(
        "pry_mcp_conformance", REPO / "scripts" / "mcp_conformance.py"
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def auth_key() -> Any:
    """Install the known key *after* the suite-wide ``pry_test_auth`` clears it.

    ``tests/conftest.py`` blanks ``settings.api_key`` for every test so the
    suite never spends the real gopass secret. The autouse fixture runs first;
    this one restores a known key for the duration of the test.
    """
    from pry.core import settings as settings_mod

    previous = settings_mod.settings.api_key
    settings_mod.settings.api_key = API_KEY
    try:
        yield API_KEY
    finally:
        settings_mod.settings.api_key = previous


@pytest.fixture(scope="module")
def live_server() -> Any:
    """Serve ``pry_mcp.asgi:app`` over real HTTP."""
    import uvicorn

    port = _free_port()
    config = uvicorn.Config(
        "pry_mcp.asgi:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="pry-mcp-conformance", daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline and thread.is_alive():
        time.sleep(0.05)
    if not server.started:
        pytest.fail("uvicorn did not start within 20s")
    try:
        yield f"http://127.0.0.1:{port}/", API_KEY
    finally:
        server.should_exit = True
        thread.join(timeout=10)


# ── revision matrix (real HTTP + SSE) ────────────────────────────────


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


# ── official SDK session ─────────────────────────────────────────────


def _assert_sdk_handshake(result) -> None:
    """The SDK can only ask for its newest handshake; the server echoes it."""
    import mcp.client.session as sdk_session
    import mcp.types

    latest_handshake = getattr(sdk_session, "LATEST_HANDSHAKE_VERSION", None)
    handshake_versions = getattr(sdk_session, "HANDSHAKE_PROTOCOL_VERSIONS", None)
    if latest_handshake is None:  # mcp 1.x has no modern handshake constants
        latest_handshake = mcp.types.LATEST_PROTOCOL_VERSION
        handshake_versions = sdk_session.SUPPORTED_PROTOCOL_VERSIONS

    assert result["protocol_version"] == latest_handshake
    assert result["protocol_version"] in handshake_versions
    assert result["server_info"]["name"] == "pry"


def _assert_sdk_surface(result) -> None:
    """Tool/resource/prompt surface and structured-content round-trip."""
    assert result["tool_count"] == len(PRY_TOOLS) == 99
    assert result["free_tool"] == {
        "name": "pry_scrape_methods",
        "is_error": False,
        "structured": True,
    }
    assert result["structured_tool"]["is_error"] is False
    assert result["structured_tool"]["count"] == 1
    assert result["structured_tool"]["total"] >= 1
    assert result["resource_count"] == len(PRY_RESOURCES) == 6
    assert result["prompt_count"] == len(PRY_PROMPTS) == 7


async def test_official_sdk_session_full_surface(
    conformance: ModuleType, live_server: Any, auth_key: str
) -> None:
    url, key = live_server
    assert key == auth_key  # the server really is using this key
    result = await conformance.run_sdk_session(url, key)

    assert result["errors"] == [], result
    _assert_sdk_handshake(result)
    _assert_sdk_surface(result)


def test_tools_call_requires_the_bearer_header(live_server: Any, auth_key: str) -> None:
    """Loopback is not a credential once PRY_API_KEY is configured."""
    url, key = live_server
    call = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "pry_scrape_methods", "arguments": {}},
    }
    with httpx.Client(timeout=10) as client:
        init = client.post(
            url,
            headers={"Accept": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1"},
                },
            },
        )
        session_id = init.headers["mcp-session-id"]
        headers = {"Accept": "application/json", "Mcp-Session-Id": session_id}

        anonymous = client.post(url, headers=headers, json=call)
        assert anonymous.status_code == 401
        assert anonymous.json()["error"]["code"] == -32001

        authorized = client.post(
            url, headers={**headers, "Authorization": f"Bearer {key}"}, json=call
        )
        assert authorized.status_code == 200
        assert authorized.json()["result"]["isError"] is False


def _modern_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }


def _modern_meta() -> dict[str, Any]:
    return {
        MCP_PROTOCOL_VERSION_META_KEY: MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "pytest-modern", "version": "1"},
    }


def _rpc(message_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def test_modern_discover_payload_matches_the_constant(live_server: Any) -> None:
    """Discovery is public, stateless and exactly the shared constant."""
    url, _ = live_server
    with httpx.Client(timeout=10) as client:
        response = client.post(
            url,
            headers=_modern_headers(),
            json=_rpc(1, MCP_DISCOVER_METHOD, {"_meta": _modern_meta()}),
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
            headers={**_modern_headers(), "Mcp-Session-Id": "stale-legacy-session"},
            json=_rpc(6, MCP_DISCOVER_METHOD, {"_meta": _modern_meta()}),
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
            headers=_modern_headers(),
            json=_rpc(
                2,
                "tools/call",
                {"_meta": _modern_meta(), "name": "pry_scrape_methods", "arguments": {}},
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
            json=_rpc(3, "tools/list", {"_meta": {MCP_PROTOCOL_VERSION_META_KEY: "2099-01-01"}}),
        )
    error = response.json()["error"]
    assert error["code"] == MCP_UNSUPPORTED_VERSION_CODE
    assert error["data"]["requested"] == "2099-01-01"
    assert MCP_PROTOCOL_VERSION in error["data"]["supported"]


def test_legacy_initialize_still_negotiates_2025_11_25(live_server: Any) -> None:
    """The legacy handshake is unchanged by the modern addition."""
    url, _ = live_server
    with httpx.Client(timeout=10) as client:
        response = client.post(
            url,
            headers={"Accept": "application/json"},
            json=_rpc(
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
            url, headers={"Accept": "application/json"}, json=_rpc(5, "does/not/exist")
        )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32601
