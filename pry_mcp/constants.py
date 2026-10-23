"""Pry - MCP server constants."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

# MCP protocol ceiling. Source of truth: official spec (latest 2026-07-28).
# Never hardcode this string elsewhere — import the constant.
MCP_PROTOCOL_VERSION = "2026-07-28"

# Revisions this server can speak. The installed Python SDK may lag the spec,
# so a client that asks for an older supported revision is answered with that
# revision; anything unknown gets the ceiling.
SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    "2026-07-28",
)


def negotiate_protocol_version(requested: str | None) -> str:
    """Return the revision to advertise for a client's ``initialize`` request."""
    if requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return MCP_PROTOCOL_VERSION


SERVER_NAME = "pry"
SERVER_VERSION = "3.0.0"

DEFAULT_BASE_URL = (
    os.getenv("PRY_URL") or os.getenv("PRY_API_URL") or "http://localhost:8002"
)

# ── Modern (2026-07-28+) discovery ───────────────────────────────────
# Pry is dual-era: legacy clients handshake with ``initialize`` (2025-11-25
# and earlier); modern clients declare their revision per request and MAY
# call ``server/discover`` first. The payload is defined once here so every
# surface — the fallback server over stdio/HTTP and the legacy SSE transport
# — answers identically.
MCP_DISCOVER_METHOD = "server/discover"
MCP_SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"
MCP_PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
MCP_RESULT_TYPE_COMPLETE = "complete"
MCP_DISCOVER_TTL_MS = 3_600_000
MCP_DISCOVER_CACHE_SCOPE = "public"
MCP_DISCOVER_INSTRUCTIONS = (
    "Pry provides web scraping, extraction, and crypto-market intelligence "
    "tools. Discovery methods are public; tools/call requires a PRY_API_KEY "
    "Bearer credential or an x402 payment."
)

# One capability definition for both eras: ``initialize`` (legacy) and
# ``server/discover`` (modern) must never advertise different surfaces.
MCP_SERVER_CAPABILITIES: dict[str, Any] = {
    "tools": {"listChanged": True},
    "resources": {"subscribe": True, "listChanged": True},
    "prompts": {"listChanged": True},
    "logging": {},
}

# JSON-RPC code for UnsupportedProtocolVersionError (spec 2026-07-28).
MCP_UNSUPPORTED_VERSION_CODE = -32022


def server_info() -> dict[str, str]:
    """Server identity, as the spec places it in ``_meta[serverInfo]``."""
    return {"name": SERVER_NAME, "version": SERVER_VERSION}


def server_capabilities() -> dict[str, Any]:
    """A fresh capabilities object; callers never mutate the constant."""
    return deepcopy(MCP_SERVER_CAPABILITIES)


def unsupported_version_data(requested: str) -> dict[str, Any]:
    """The ``data`` payload of an UnsupportedProtocolVersionError."""
    return {"supported": list(SUPPORTED_PROTOCOL_VERSIONS), "requested": requested}


def discover_result() -> dict[str, Any]:
    """The ``server/discover`` result for the 2026-07-28 revision.

    Fields are the spec's DiscoverResult: ``resultType``, ``supportedVersions``,
    ``capabilities``, ``_meta[serverInfo]``, plus optional ``instructions``
    and the caching hints ``ttlMs`` / ``cacheScope``.
    """
    return {
        "resultType": MCP_RESULT_TYPE_COMPLETE,
        "supportedVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "capabilities": server_capabilities(),
        "_meta": {MCP_SERVER_INFO_META_KEY: server_info()},
        "instructions": MCP_DISCOVER_INSTRUCTIONS,
        "ttlMs": MCP_DISCOVER_TTL_MS,
        "cacheScope": MCP_DISCOVER_CACHE_SCOPE,
    }
