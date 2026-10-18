# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared fixtures and helpers for the MCP client conformance tests.

The suite is split by subject — legacy revisions, modern discovery,
official SDK session, and auth — but all of them need the same things:
the shipped runner module loaded by path, a real uvicorn server on a
loopback port (the SDK's Streamable HTTP transport is not exercised by
``TestClient``), and a known API key.
"""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from pry_mcp.constants import MCP_PROTOCOL_VERSION, MCP_PROTOCOL_VERSION_META_KEY

if TYPE_CHECKING:
    from types import ModuleType

REPO = Path(__file__).resolve().parents[1]
API_KEY = "conformance-key"
UNKNOWN_REVISIONS = ("1999-01-01", "not-a-revision")


def free_port() -> int:
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

    port = free_port()
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


def rpc(message_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def modern_headers(version: str = MCP_PROTOCOL_VERSION) -> dict[str, str]:
    return {"Accept": "application/json", "MCP-Protocol-Version": version}


def modern_meta(version: str = MCP_PROTOCOL_VERSION) -> dict[str, Any]:
    return {
        MCP_PROTOCOL_VERSION_META_KEY: version,
        "io.modelcontextprotocol/clientInfo": {"name": "pytest-modern", "version": "1"},
    }
