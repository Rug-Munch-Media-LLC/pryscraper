# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Official SDK session: what ``mcp.ClientSession`` actually gets from Pry.

SDK facts recorded here (official ``mcp`` 2.2.0):

* ``ClientSession.initialize()`` always requests ``LATEST_HANDSHAKE_VERSION``
  (2025-11-25). It has no per-call version argument, so the per-revision
  matrix is driven with raw ``initialize`` requests — an SDK limitation, not a
  server limitation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pry_mcp import PRY_PROMPTS, PRY_RESOURCES, PRY_TOOLS
from tests.conformance_support import (  # noqa: F401 - fixtures
    auth_key,
    conformance,
    live_server,
)

if TYPE_CHECKING:
    from types import ModuleType


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
