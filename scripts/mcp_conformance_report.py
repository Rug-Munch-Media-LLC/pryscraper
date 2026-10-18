#!/usr/bin/env python3
"""Reporting and CLI wiring for the MCP conformance runner."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mcp_conformance_modern import run_modern_session  # noqa: E402
from mcp_conformance_sessions import run_sdk_session  # noqa: E402
from mcp_conformance_transport import run_wire_matrix  # noqa: E402

from pry_mcp.constants import MCP_PROTOCOL_VERSION  # noqa: E402

DESCRIPTION = "Run MCP client conformance checks against a live Pry server."


def print_matrix(matrix: dict[str, Any], sdk: dict[str, Any] | None) -> None:
    """Print the per-revision matrix, plus the SDK session row when it ran."""
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
        "initialize requests. 2026-07-28 is a modern revision reached through "
        "server/discover, which this server implements — see the modern session."
    )


def print_failures(
    matrix: dict[str, Any], sdk: dict[str, Any] | None, modern: dict[str, Any] | None
) -> None:
    """Print the matrix, SDK and modern-session failure detail behind a FAIL."""
    if matrix["errors"]:
        print("matrix failures:")
        for error in matrix["errors"]:
            print(f"  - {error}")
    for label, payload in (("SDK", sdk), ("modern", modern)):
        if payload is None:
            continue
        print(f"{label} checks:")
        for name, check in payload["checks"].items():
            detail = check["detail"] if check["detail"] is not None else ""
            print(f"  {'PASS' if check['ok'] else 'FAIL'}  {name}  {detail}")
        if payload["errors"]:
            print(f"{label} failures:")
            for error in payload["errors"]:
                print(f"  - {error}")


async def _run_sdk(url: str, key: str) -> dict[str, Any] | None:
    """Run the SDK session when a key is supplied; never raise."""
    if not key:
        print("AUTH: no --key / PRY_API_KEY — tools/call checks skipped", file=sys.stderr)
        return None
    try:
        return await run_sdk_session(url, key)
    except Exception as exc:  # noqa: BLE001 - surface the failed stage
        return {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"], "checks": {}}


async def _main(args: argparse.Namespace) -> int:
    matrix = await run_wire_matrix(args.url, args.timeout)
    sdk = await _run_sdk(args.url, args.key)
    modern = await run_modern_session(args.url, args.key)
    print_matrix(matrix, sdk)
    print(
        f"modern session  {MCP_PROTOCOL_VERSION:<14} "
        f"{modern.get('tool_count', '-'):>5}  {'ok' if modern['ok'] else 'FAIL'}"
    )
    ok = not matrix["errors"] and (sdk is None or sdk["ok"]) and modern["ok"]
    print_failures(matrix, sdk, modern)
    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
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
