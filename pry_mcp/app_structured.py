# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Populate ``structuredContent`` on MCP ``tools/call`` responses.

Split out of ``pry_mcp/app.py`` (the transport rehydration step) so the JSON-RPC
handler stays below the complexity gate.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _tool_spec(server: Any, name: Any) -> dict[str, Any] | None:
    """Return the tool spec for ``name`` from either server shape.

    The fallback server keeps tools as a name-keyed dict; the SDK/facade
    variants expose a list.
    """
    tools = getattr(server, "tools", None) or {}
    if isinstance(tools, dict):
        spec = tools.get(name)
    else:
        spec = next(
            (tool for tool in tools if isinstance(tool, dict) and tool.get("name") == name),
            None,
        )
    return spec if isinstance(spec, dict) else None


def _text_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    """Decode the first JSON-object text block of a tool result, if any."""
    for block in result.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        try:
            payload = json.loads(block.get("text", ""))
        except (TypeError, ValueError) as e:
            logger.debug(
                "mcp_text_block_not_json",
                extra={"error": str(e), "error_type": type(e).__name__},
            )
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _attach_structured_content(
    response: dict[str, Any], server: Any, request_body: dict[str, Any]
) -> dict[str, Any]:
    """Populate ``structuredContent`` for successful ``tools/call`` responses.

    Every Pry tool declares an ``outputSchema``. Per the MCP spec a tool that
    advertises an output schema MUST return ``structuredContent``; the official
    SDK client raises
    ``Tool <name> has an output schema but did not return structured content``
    and discards an otherwise valid result. The fallback server returns the
    payload as a JSON text block only, so this transport layer rehydrates the
    object from that block. Non-object payloads (arrays/scalars), errors and
    tools without an output schema are left untouched.
    """
    if request_body.get("method") != "tools/call":
        return response
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError"):
        return response
    if "structuredContent" in result:
        return response
    name = (request_body.get("params") or {}).get("name")
    spec = _tool_spec(server, name)
    if spec is None or not spec.get("outputSchema"):
        return response
    payload = _text_payload(result)
    if payload is not None:
        result["structuredContent"] = payload
    return response
