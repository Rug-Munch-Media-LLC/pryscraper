# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared fixtures for the MCP quality audit package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from ._support import _server

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient


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
