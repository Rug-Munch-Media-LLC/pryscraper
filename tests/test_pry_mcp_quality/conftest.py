# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared fixtures for the MCP quality audit package."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import pytest

from ._support import _server

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient


def _close_sync(client: Any) -> None:
    """Close an httpx client from a synchronous teardown.

    No event loop is running inside a sync fixture, so a fresh loop is safe;
    a loop that refuses to close (already torn down) is ignored -- the client
    is unreachable either way.
    """
    with suppress(RuntimeError):
        asyncio.run(client.aclose())


@pytest.fixture(autouse=True)
def _clear_hot_tool_cache() -> Iterator[None]:
    """Reset the dispatch-level 10s hot-tool cache before every test.

    ``combined_tool_executor`` memoizes hot tools (odds, serp, ...) for 10
    seconds; without a reset, a success-path test caches a result that a
    later missing-module test would read back instead of the readable
    "not available" message.
    """
    import pry_mcp.fallback_server as _fallback

    _fallback._hot_tool_cache.clear()
    yield
    _fallback._hot_tool_cache.clear()


@pytest.fixture(autouse=True)
def _reset_shared_http_client() -> Iterator[None]:
    """Drop the process-wide httpx client so REST-proxy tests stay hermetic.

    ``pry.core.client`` caches its ``AsyncClient`` in the module global
    ``http_client``. The REST round-trip tests patch
    ``pry_mcp.fallback_server.httpx.AsyncClient`` to intercept outbound
    calls -- but ``fallback_server`` builds its client through
    ``get_client()``, which imports ``pry.core.client`` and returns the
    cached global. Once any earlier test (in this package or a sibling)
    populates that global, the patch is a no-op, the tool makes a real
    network call, and every ``test_rest_proxy_tool_success`` case fails
    with ``isError=True`` while passing in isolation.

    Clearing the global before and after each test restores isolation; a stale
    client found at teardown is closed so its connection pool is not leaked.
    This is test-only state hygiene -- no production behaviour changes.
    """
    import pry.core.client as _client

    _client.http_client = None
    yield
    stale, _client.http_client = _client.http_client, None
    if stale is not None:
        _close_sync(stale)


def _make_app() -> Any:
    from pry_mcp.app import create_mcp_app

    return create_mcp_app(get_server=lambda: _server())


@pytest.fixture
def mcp_client() -> Iterator[TestClient]:
    """TestClient over the standalone MCP app with a fresh server per test."""
    from fastapi.testclient import TestClient

    from pry_mcp.app import _MCP_SESSIONS

    _MCP_SESSIONS.clear()
    with TestClient(_make_app()) as client:
        yield client
    _MCP_SESSIONS.clear()
