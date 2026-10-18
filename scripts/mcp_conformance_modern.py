#!/usr/bin/env python3
"""Modern (2026-07-28-only) MCP client conformance.

No ``initialize``: discovery, listing and execution all carry the revision in
``_meta`` and in the ``MCP-Protocol-Version`` header. Discovery stays public;
``tools/call`` still needs the Bearer key.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mcp_conformance_transport import (  # noqa: E402
    ACCEPT,
    EXPECTED_TOOLS,
    check,
    decode,
    new_result,
    rpc,
)

from pry_mcp.constants import (  # noqa: E402
    MCP_DISCOVER_METHOD,
    MCP_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION_META_KEY,
    MCP_SERVER_INFO_META_KEY,
    SERVER_NAME,
)


@dataclass(frozen=True)
class ModernRequest:
    """Everything a 2026-07-28 request carries: endpoint, headers, _meta."""

    url: str
    headers: dict[str, str]
    meta: dict[str, Any]


def _modern_request(url: str) -> ModernRequest:
    return ModernRequest(
        url=url,
        headers={
            "Accept": ACCEPT,
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        },
        meta={
            MCP_PROTOCOL_VERSION_META_KEY: MCP_PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientInfo": {
                "name": "pry-conformance-modern",
                "version": "1",
            },
        },
    )


async def _discover(client: httpx.AsyncClient, req: ModernRequest, result: dict[str, Any]) -> None:
    discovered = await client.post(
        req.url, headers=req.headers, json=rpc(1, MCP_DISCOVER_METHOD, {"_meta": req.meta})
    )
    discover_body = decode(discovered)
    discover = discover_body.get("result") or {}
    supported = discover.get("supportedVersions") or []
    check(result, "server/discover", discovered.status_code == 200, discovered.status_code)
    check(result, "supportedVersions", MCP_PROTOCOL_VERSION in supported, supported)
    info = (discover.get("_meta") or {}).get(MCP_SERVER_INFO_META_KEY) or {}
    check(result, "serverInfo", info.get("name") == SERVER_NAME, info)
    check(result, "discover is public", "error" not in discover_body, discover_body.get("error"))
    result["supported_versions"] = supported


async def _modern_tools(
    client: httpx.AsyncClient, req: ModernRequest, result: dict[str, Any]
) -> None:
    listed = await client.post(
        req.url, headers=req.headers, json=rpc(2, "tools/list", {"_meta": req.meta})
    )
    tools = (decode(listed).get("result") or {}).get("tools") or []
    result["tool_count"] = len(tools)
    check(result, "tools/list", len(tools) == EXPECTED_TOOLS, len(tools))


async def _modern_call(
    client: httpx.AsyncClient, req: ModernRequest, key: str, result: dict[str, Any]
) -> None:
    called = await client.post(
        req.url,
        headers={**req.headers, "Authorization": f"Bearer {key}"},
        json=rpc(
            3,
            "tools/call",
            {"_meta": req.meta, "name": "pry_scrape_methods", "arguments": {}},
        ),
    )
    call_result = decode(called).get("result") or {}
    result["tools_call"] = {
        "http_status": called.status_code,
        "is_error": bool(call_result.get("isError", True)),
    }
    check(result, "tools/call", called.status_code == 200, called.status_code)
    check(result, "tools/call result", call_result.get("isError") is False, call_result)


async def run_modern_session(url: str, key: str | None) -> dict[str, Any]:
    """Exercise a modern (2026-07-28-only) client against the dual-era server.

    No ``initialize``: discovery, listing and execution all carry the revision
    in ``_meta`` and in the ``MCP-Protocol-Version`` header. Discovery stays
    public; ``tools/call`` still needs the Bearer key.
    """
    result = new_result()
    req = _modern_request(url)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _discover(client, req, result)
        await _modern_tools(client, req, result)
        if key:
            await _modern_call(client, req, key, result)
        else:
            result["tools_call"] = "skipped (no key)"
    result["ok"] = not result["errors"]
    return result
