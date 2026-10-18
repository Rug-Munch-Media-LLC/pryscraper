#!/usr/bin/env python3
"""Wire-level MCP conformance probes.

The per-revision matrix is the only way to ask for a *specific* revision:
the official Python SDK's ``ClientSession.initialize()`` always sends
``LATEST_HANDSHAKE_VERSION``. Each row is one raw ``initialize`` (asking for a
declared revision, an unknown one, or the ceiling) followed by ``tools/list``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for _path in (str(ROOT), str(SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from pry_mcp import PRY_TOOLS  # noqa: E402
from pry_mcp.constants import (  # noqa: E402
    MCP_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
)

UNKNOWN_VERSION = "1999-01-01"
EXPECTED_TOOLS = len(PRY_TOOLS)
EXPECTED_CEILING = MCP_PROTOCOL_VERSION
MATRIX_VERSIONS = (*SUPPORTED_PROTOCOL_VERSIONS, UNKNOWN_VERSION)

ACCEPT = "application/json, text/event-stream"


def new_result() -> dict[str, Any]:
    """A fresh ``{"checks": ..., "errors": ...}`` accumulator."""
    return {"checks": {}, "errors": []}


def check(result: dict[str, Any], name: str, condition: bool, detail: Any = None) -> None:
    """Record one named check and its failure message."""
    result["checks"][name] = {"ok": bool(condition), "detail": detail}
    if not condition:
        result["errors"].append(f"{name}: {detail}")


def decode(response: httpx.Response) -> dict[str, Any]:
    """Decode a JSON or single-event SSE JSON-RPC response."""
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:") :].strip())
        raise ValueError(f"SSE response carried no data event: {response.text[:200]}")
    return response.json()


def rpc(message_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


async def _handshake(client: httpx.AsyncClient, url: str, requested: str) -> dict[str, Any]:
    """Ask for one revision explicitly and keep what the server answered."""
    response = await client.post(
        url,
        headers={"Accept": ACCEPT, "Content-Type": "application/json"},
        json=rpc(
            1,
            "initialize",
            {
                "protocolVersion": requested,
                "capabilities": {},
                "clientInfo": {"name": "pry-conformance", "version": "1"},
            },
        ),
    )
    body = decode(response)
    return {
        "negotiated": (body.get("result") or {}).get("protocolVersion"),
        "session_id": bool(response.headers.get("mcp-session-id", "")),
        "http_status": response.status_code,
        "_session": response.headers.get("mcp-session-id", ""),
    }


async def _tools(client: httpx.AsyncClient, url: str, session_id: str) -> int:
    listed = await client.post(
        url,
        headers={
            "Accept": ACCEPT,
            "Content-Type": "application/json",
            "Mcp-Session-Id": session_id,
        },
        json=rpc(2, "tools/list"),
    )
    tools = ((decode(listed).get("result") or {}).get("tools")) or []
    return len(tools)


async def _probe_revision(client: httpx.AsyncClient, url: str, requested: str) -> dict[str, Any]:
    """One initialize + tools/list round trip, never raising."""
    row: dict[str, Any] = {"requested": requested}
    try:
        row.update(await _handshake(client, url, requested))
        row["tools"] = await _tools(client, url, row.pop("_session"))
        expected = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else EXPECTED_CEILING
        row["expected"] = expected
        row["ok"] = row["negotiated"] == expected and row["tools"] == EXPECTED_TOOLS
    except Exception as exc:  # noqa: BLE001 - report, do not abort the matrix
        row["ok"] = False
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def _failure(row: dict[str, Any]) -> str:
    if "error" in row:
        return f"{row['requested']}: {row['error']}"
    return (
        f"{row['requested']}: negotiated={row['negotiated']} expected={row['expected']} "
        f"tools={row['tools']} expected_tools={EXPECTED_TOOLS}"
    )


async def run_wire_matrix(
    url: str, request_timeout: float, extra_versions: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Ask for each revision explicitly and record what the server answers."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    versions = (*MATRIX_VERSIONS, *extra_versions)
    async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=True) as client:
        for requested in versions:
            row = await _probe_revision(client, url, requested)
            if not row["ok"]:
                errors.append(_failure(row))
            rows.append(row)
    return {"rows": rows, "errors": errors}
