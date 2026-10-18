"""Pry — modern (2026-07-28+) protocol-era helpers, shared by all transports.

A dual-era server accepts both idioms: legacy clients handshake with
``initialize``, modern clients declare their revision per request. These
helpers keep the era rules in one place so the stdio/HTTP JSON-RPC path and
the Streamable HTTP header path cannot disagree.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pry_mcp.constants import (
    MCP_PROTOCOL_VERSION_META_KEY,
    MCP_UNSUPPORTED_VERSION_CODE,
    SUPPORTED_PROTOCOL_VERSIONS,
    unsupported_version_data,
)


def declared_protocol_version(params: Any) -> str | None:
    """The modern per-request revision from ``params._meta``, if declared."""
    if not isinstance(params, dict):
        return None
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return None
    version = meta.get(MCP_PROTOCOL_VERSION_META_KEY)
    return version if isinstance(version, str) and version else None


def version_rejection(req_id: Any, requested: str | None) -> dict[str, Any] | None:
    """An UnsupportedProtocolVersionError envelope, or ``None`` when fine.

    Callers pass the declared revision from whichever surface carries it —
    ``_meta`` on stdio/JSON-RPC, ``MCP-Protocol-Version`` on HTTP.
    """
    if not requested or requested in SUPPORTED_PROTOCOL_VERSIONS:
        return None
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": MCP_UNSUPPORTED_VERSION_CODE,
            "message": "Unsupported protocol version",
            "data": unsupported_version_data(requested),
        },
    }
