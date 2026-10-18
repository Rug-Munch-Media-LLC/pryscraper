#!/usr/bin/env python3
"""Official MCP SDK client conformance session.

* **Official SDK session** — ``mcp.ClientSession`` over Streamable HTTP:
  initialize, list tools, call a free and a structured tool, list resources,
  subscribe to a resource, list prompts.

The 2026-07-28-only (modern) client lives in ``mcp_conformance_modern``.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mcp_conformance_transport import (  # noqa: E402
    EXPECTED_TOOLS,
    check,
    new_result,
)


def sdk_field(obj: Any, snake: str, camel: str, default: Any = None) -> Any:
    """Read a result field across SDK generations (1.x camelCase, 2.x snake)."""
    value = getattr(obj, snake, None)
    return value if value is not None else getattr(obj, camel, default)


def _sdk_handshake(init: Any, result: dict[str, Any]) -> None:
    version = sdk_field(init, "protocol_version", "protocolVersion")
    info = sdk_field(init, "server_info", "serverInfo")
    result["protocol_version"] = version
    result["server_info"] = info.model_dump(mode="json") if hasattr(info, "model_dump") else info
    check(result, "initialize", bool(version), version)


async def _sdk_tools(session: Any, result: dict[str, Any]) -> None:
    tools = await session.list_tools()
    names = [tool.name for tool in tools.tools]
    result["tool_count"] = len(names)
    check(result, "tools/list", len(names) == EXPECTED_TOOLS, len(names))

    free = await session.call_tool("pry_scrape_methods", {})
    free_structured = sdk_field(free, "structured_content", "structuredContent")
    free_is_error = bool(sdk_field(free, "is_error", "isError", False))
    result["free_tool"] = {
        "name": "pry_scrape_methods",
        "is_error": free_is_error,
        "structured": isinstance(free_structured, dict),
    }
    check(result, "call free tool", not free_is_error, "pry_scrape_methods")
    check(result, "free tool structuredContent", isinstance(free_structured, dict), None)

    structured = await session.call_tool("pry_actor_catalog", {"limit": 1})
    payload = sdk_field(structured, "structured_content", "structuredContent") or {}
    structured_is_error = bool(sdk_field(structured, "is_error", "isError", False))
    result["structured_tool"] = {
        "name": "pry_actor_catalog",
        "is_error": structured_is_error,
        "count": payload.get("count"),
        "total": payload.get("total"),
    }
    check(result, "call structured tool", not structured_is_error, "pry_actor_catalog")
    check(result, "structured tool payload", payload.get("count") == 1, payload.get("count"))


async def _sdk_resources(session: Any, result: dict[str, Any]) -> None:
    resources = await session.list_resources()
    result["resource_count"] = len(resources.resources)
    check(result, "resources/list", bool(resources.resources), len(resources.resources))

    with warnings.catch_warnings():
        # resources/subscribe is removed in the 2026-07-28 modern revision;
        # it is valid at the 2025-11-25 handshake we negotiate, so the SDK
        # warns but still sends it.
        warnings.simplefilter("ignore")
        await session.subscribe_resource("pry://catalog")
    check(result, "resources/subscribe", True, "pry://catalog")

    prompts = await session.list_prompts()
    result["prompt_count"] = len(prompts.prompts)
    check(result, "prompts/list", bool(prompts.prompts), len(prompts.prompts))


async def run_sdk_session(url: str, key: str | None) -> dict[str, Any]:
    """Exercise the server through the official MCP Python SDK client."""
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    result = new_result()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    # The SDK's httpx2.Timeout is not httpx.Timeout; use the SDK defaults
    # (30s connect / 300s stream read) rather than mixing the two clients.
    http_client = create_mcp_http_client(headers=headers)
    async with (
        http_client,
        # mcp 1.29 yields (read, write, get_session_id); earlier builds
        # yielded two streams. Accept both so the shipped runner works across
        # the SDK range the project declares.
        streamable_http_client(url, http_client=http_client) as (read, write, *_),
        ClientSession(read, write) as session,
    ):
        _sdk_handshake(await session.initialize(), result)
        await _sdk_tools(session, result)
        await _sdk_resources(session, result)
    result["ok"] = not result["errors"]
    return result
