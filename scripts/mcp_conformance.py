#!/usr/bin/env python3
"""Run MCP client conformance checks against a live Pry server.

Two layers, deliberately:

* **Wire matrix** — raw ``initialize`` requests at every revision Pry claims
  to speak, plus an unknown revision, each followed by ``tools/list``. This is
  the only way to request a *specific* revision: the official Python SDK's
  ``ClientSession.initialize()`` always sends ``LATEST_HANDSHAKE_VERSION``.
* **Official SDK session** — ``mcp.ClientSession`` over Streamable HTTP:
  initialize, list tools, call two tools (one free and one structured),
  list resources, subscribe to a resource, list prompts.

Usage::

    python scripts/mcp_conformance.py --url http://127.0.0.1:8006/ --key "$PRY_API_KEY"

Exit code 0 when every executed check passes, 1 otherwise. Without ``--key``
the tool-call checks are skipped (discovery still runs) and the matrix is
still printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def _decode(response: httpx.Response) -> dict[str, Any]:
    """Decode a JSON or single-event SSE JSON-RPC response."""
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:") :].strip())
        raise ValueError(f"SSE response carried no data event: {response.text[:200]}")
    return response.json()


def _rpc(message_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


async def run_wire_matrix(
    url: str, request_timeout: float, extra_versions: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Ask for each revision explicitly and record what the server answers."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    versions = (*MATRIX_VERSIONS, *extra_versions)
    async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=True) as client:
        for requested in versions:
            row: dict[str, Any] = {"requested": requested}
            try:
                init = await client.post(
                    url,
                    headers={"Accept": ACCEPT, "Content-Type": "application/json"},
                    json=_rpc(
                        1,
                        "initialize",
                        {
                            "protocolVersion": requested,
                            "capabilities": {},
                            "clientInfo": {"name": "pry-conformance", "version": "1"},
                        },
                    ),
                )
                session_id = init.headers.get("mcp-session-id", "")
                init_body = _decode(init)
                row["negotiated"] = (init_body.get("result") or {}).get("protocolVersion")
                row["session_id"] = bool(session_id)
                row["http_status"] = init.status_code

                listed = await client.post(
                    url,
                    headers={
                        "Accept": ACCEPT,
                        "Content-Type": "application/json",
                        "Mcp-Session-Id": session_id,
                    },
                    json=_rpc(2, "tools/list"),
                )
                tools = ((_decode(listed).get("result") or {}).get("tools")) or []
                row["tools"] = len(tools)

                expected = (
                    requested if requested in SUPPORTED_PROTOCOL_VERSIONS else EXPECTED_CEILING
                )
                row["expected"] = expected
                row["ok"] = row["negotiated"] == expected and row["tools"] == EXPECTED_TOOLS
                if not row["ok"]:
                    errors.append(
                        f"{requested}: negotiated={row['negotiated']} expected={expected} "
                        f"tools={row['tools']} expected_tools={EXPECTED_TOOLS}"
                    )
            except Exception as exc:  # noqa: BLE001 - report, do not abort the matrix
                row["ok"] = False
                row["error"] = f"{type(exc).__name__}: {exc}"
                errors.append(f"{requested}: {row['error']}")
            rows.append(row)
    return {"rows": rows, "errors": errors}


async def run_sdk_session(url: str, key: str | None) -> dict[str, Any]:
    """Exercise the server through the official MCP Python SDK client."""
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    result: dict[str, Any] = {"checks": {}, "errors": []}

    def check(name: str, condition: bool, detail: Any = None) -> None:
        result["checks"][name] = {"ok": bool(condition), "detail": detail}
        if not condition:
            result["errors"].append(f"{name}: {detail}")

    headers = {"Authorization": f"Bearer {key}"} if key else {}
    # The SDK's httpx2.Timeout is not httpx.Timeout; use the SDK defaults
    # (30s connect / 300s stream read) rather than mixing the two clients.
    http_client = create_mcp_http_client(headers=headers)
    async with (
        http_client,
        streamable_http_client(url, http_client=http_client) as (read, write),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        result["protocol_version"] = init.protocol_version
        result["server_info"] = init.server_info.model_dump(mode="json")
        check("initialize", bool(init.protocol_version), init.protocol_version)

        tools = await session.list_tools()
        names = [tool.name for tool in tools.tools]
        result["tool_count"] = len(names)
        check("tools/list", len(names) == EXPECTED_TOOLS, len(names))

        free = await session.call_tool("pry_scrape_methods", {})
        free_structured = getattr(free, "structured_content", None)
        result["free_tool"] = {
            "name": "pry_scrape_methods",
            "is_error": bool(getattr(free, "is_error", False)),
            "structured": isinstance(free_structured, dict),
        }
        check("call free tool", not free.is_error, "pry_scrape_methods")
        check("free tool structuredContent", isinstance(free_structured, dict), None)

        structured = await session.call_tool("pry_actor_catalog", {"limit": 1})
        payload = getattr(structured, "structured_content", None) or {}
        result["structured_tool"] = {
            "name": "pry_actor_catalog",
            "is_error": bool(getattr(structured, "is_error", False)),
            "count": payload.get("count"),
            "total": payload.get("total"),
        }
        check("call structured tool", not structured.is_error, "pry_actor_catalog")
        check("structured tool payload", payload.get("count") == 1, payload.get("count"))

        resources = await session.list_resources()
        result["resource_count"] = len(resources.resources)
        check("resources/list", bool(resources.resources), len(resources.resources))

        with warnings.catch_warnings():
            # resources/subscribe is removed in the 2026-07-28 modern
            # revision; it is valid at the 2025-11-25 handshake we
            # negotiate, so the SDK warns but still sends it.
            warnings.simplefilter("ignore")
            await session.subscribe_resource("pry://catalog")
        check("resources/subscribe", True, "pry://catalog")

        prompts = await session.list_prompts()
        result["prompt_count"] = len(prompts.prompts)
        check("prompts/list", bool(prompts.prompts), len(prompts.prompts))

    result["ok"] = not result["errors"]
    return result


def _print_matrix(matrix: dict[str, Any], sdk: dict[str, Any] | None) -> None:
    print()
    print(f"{'requested':<14} {'negotiated':<14} {'tools':>5}  result")
    print("-" * 52)
    for row in matrix["rows"]:
        print(
            f"{row['requested']:<14} {row.get('negotiated', '-'):<14} "
            f"{row.get('tools', '-'):>5}  {'ok' if row.get('ok') else 'FAIL'}"
        )
    if sdk is not None:
        print("-" * 52)
        print(
            f"{'SDK session':<14} {sdk.get('protocol_version', '-'):<14} "
            f"{sdk.get('tool_count', '-'):>5}  {'ok' if sdk.get('ok') else 'FAIL'}"
        )
    print()
    print(
        "SDK note: ClientSession.initialize() always requests "
        "LATEST_HANDSHAKE_VERSION (2025-11-25) and rejects any reply outside "
        "HANDSHAKE_PROTOCOL_VERSIONS; the per-revision rows above are raw "
        "initialize requests. 2026-07-28 is a modern revision negotiated via "
        "server/discover, which this server does not implement."
    )


async def _run_sdk(url: str, key: str) -> dict[str, Any] | None:
    """Run the SDK session when a key is supplied; never raise."""
    if not key:
        print("AUTH: no --key / PRY_API_KEY — tools/call checks skipped", file=sys.stderr)
        return None
    try:
        return await run_sdk_session(url, key)
    except Exception as exc:  # noqa: BLE001 - surface the failed stage
        return {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"], "checks": {}}


def _print_failures(matrix: dict[str, Any], sdk: dict[str, Any] | None) -> None:
    """Print the matrix and SDK failure detail behind a FAIL result."""
    if matrix["errors"]:
        print("matrix failures:")
        for error in matrix["errors"]:
            print(f"  - {error}")
    if sdk is None:
        return
    print("SDK checks:")
    for name, check in sdk["checks"].items():
        detail = check["detail"] if check["detail"] is not None else ""
        print(f"  {'PASS' if check['ok'] else 'FAIL'}  {name}  {detail}")
    if sdk["errors"]:
        print("SDK failures:")
        for error in sdk["errors"]:
            print(f"  - {error}")


async def _main(args: argparse.Namespace) -> int:
    matrix = await run_wire_matrix(args.url, args.timeout)
    sdk = await _run_sdk(args.url, args.key)
    _print_matrix(matrix, sdk)
    ok = not matrix["errors"] and (sdk is None or sdk["ok"])
    _print_failures(matrix, sdk)
    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url",
        default=os.getenv("PRY_MCP_URL", "http://127.0.0.1:8006/"),
        help="MCP Streamable HTTP endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--key",
        default=os.getenv("PRY_API_KEY", ""),
        help="Pry API key for tools/call (default: PRY_API_KEY)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="wire-matrix request timeout seconds (the SDK keeps its own defaults)",
    )
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
