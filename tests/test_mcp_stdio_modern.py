# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""stdio era coverage for every shipped Pry MCP boot path.

A modern-only client must be able to run ``server/discover`` -> ``tools/list``
-> ``tools/call`` over stdio without ever sending ``initialize``; a legacy
client must keep working through the same process. Both are asserted against
the module entry point, the ``pry mcp --stdio`` CLI path, and the wheel
console-script target.

The subprocesses are real: a banner on stdout, a legacy-only server that
rejects discovery, or a boot path that resolves a different server all fail
here. ``PRY_API_URL`` points at a closed port, so no tool call leaves the box —
``pry_scrape_methods`` executes locally.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from pry_mcp import PRY_TOOLS
from pry_mcp.constants import MCP_PROTOCOL_VERSION_META_KEY

REPO = Path(__file__).resolve().parents[1]
TOOL_NAMES = [tool["name"] for tool in PRY_TOOLS]
MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2024-11-05"

# Every shipped way to boot the stdio server. The last one is exactly what a
# wheel installs for ``pry-mcp`` / ``pryscraper-mcp`` (and accepts ``--stdio``).
BOOT_COMMANDS: dict[str, list[str]] = {
    "module": [sys.executable, "-m", "pry.api.mcp_production"],
    "cli": [sys.executable, "-m", "pry.misc.cli", "mcp", "--stdio"],
    "wheel-entrypoint": [
        sys.executable,
        "-c",
        "from pry.misc.cli_click import launch_mcp_stdio; launch_mcp_stdio()",
        "--stdio",
    ],
}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "PRY_SECRET_BACKEND": "env",
            "PRY_API_KEY": "stdio-modern-test-key",
            "PRY_API_URL": "http://127.0.0.1:1",
        }
    )
    return env


def _spawn(command: list[str]) -> tuple[subprocess.Popen[str], queue.Queue[str]]:
    proc = subprocess.Popen(  # noqa: S603 — argv is the test's own boot table
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd=str(REPO),
        env=_env(),
    )
    lines: queue.Queue[str] = queue.Queue()

    def _read() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)
        lines.put("")  # EOF sentinel

    threading.Thread(target=_read, name="pry-mcp-stdio-reader", daemon=True).start()
    return proc, lines


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        proc.kill()
        proc.wait(timeout=10)


def _stderr(proc: subprocess.Popen[str]) -> str:
    """Best-effort stderr text after the process is gone."""
    if proc.poll() is None:
        proc.terminate()
    try:
        _, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        proc.kill()
        _, err = proc.communicate(timeout=10)
    return (err or "")[:1000]


def _collect(
    proc: subprocess.Popen[str], lines: queue.Queue[str], ids: list[int], timeout: float = 60.0
) -> dict[int, dict[str, Any]]:
    responses: dict[int, dict[str, Any]] = {}
    deadline = time.monotonic() + timeout
    while len(responses) < len(ids):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(f"stdio server timed out; stderr: {_stderr(proc)}")
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:  # pragma: no cover - covered by the deadline check
            continue
        if not line:
            pytest.fail(f"stdio stream closed before answering: {_stderr(proc)}")
        payload = json.loads(line)  # a non-JSON banner is a hard failure
        if "id" in payload:
            responses[payload["id"]] = payload
    return responses


def _transact(
    command: list[str], requests: list[dict[str, Any]], ids: list[int]
) -> dict[int, dict[str, Any]]:
    proc, lines = _spawn(command)
    try:
        assert proc.stdin is not None
        for request in requests:
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()
        return _collect(proc, lines, ids)
    finally:
        _stop(proc)


def _modern_meta() -> dict[str, str]:
    return {MCP_PROTOCOL_VERSION_META_KEY: MODERN_VERSION}


def _assert_modern_discover(discover: dict) -> None:
    assert "error" not in discover, discover
    result = discover["result"]
    assert result["resultType"] == "complete"
    assert MODERN_VERSION in result["supportedVersions"]
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "pry"


def _assert_all_tools(listed: dict) -> None:
    assert "error" not in listed, listed
    assert [tool["name"] for tool in listed["result"]["tools"]] == TOOL_NAMES


@pytest.mark.parametrize("boot", BOOT_COMMANDS, ids=BOOT_COMMANDS)
def test_stdio_modern_session_never_initializes(boot: str) -> None:
    """discover -> tools/list -> tools/call, with no ``initialize`` at all."""
    meta = _modern_meta()
    responses = _transact(
        BOOT_COMMANDS[boot],
        [
            {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": meta}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": meta}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "pry_scrape_methods", "arguments": {}, "_meta": meta},
            },
        ],
        [1, 2, 3],
    )

    _assert_modern_discover(responses[1])
    _assert_all_tools(responses[2])
    assert len(TOOL_NAMES) == 99

    called = responses[3]
    assert "error" not in called, called
    assert called["result"]["isError"] is False
    assert called["result"]["content"], "a keyed local call must return content"


@pytest.mark.parametrize("boot", BOOT_COMMANDS, ids=BOOT_COMMANDS)
def test_stdio_legacy_initialize_still_works(boot: str) -> None:
    """The legacy handshake and tools/list survive on the same binary."""
    responses = _transact(
        BOOT_COMMANDS[boot],
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LEGACY_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "pytest-legacy", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
        [1, 2],
    )

    init = responses[1]
    assert "error" not in init, init
    assert init["result"]["protocolVersion"] == LEGACY_VERSION
    assert init["result"]["serverInfo"]["name"] == "pry"
    assert "tools" in init["result"]["capabilities"]

    listed = responses[2]
    assert "error" not in listed, listed
    assert [tool["name"] for tool in listed["result"]["tools"]] == TOOL_NAMES
