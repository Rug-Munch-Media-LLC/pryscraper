# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Distribution-level MCP tests: the wheel as an agent actually receives it.

Everything here is transport- and manifest-facing, not unit-level:

* the stdio entry point completes an MCP handshake and lists all 99 tools;
* the HTTP transport answers ``initialize`` / ``tools/list`` / ``health``;
* ``tools/call`` is gated (anonymous -> 401, valid Bearer -> not 401);
* every shipped manifest agrees with ``PRY_TOOLS`` and contains no dead
  (404 / codeberg) URLs.

The stdio case spawns a real subprocess so a broken console script or a
stdout banner that corrupts the JSON-RPC stream fails the suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pry_mcp import PRY_TOOLS
from pry_mcp.app import create_mcp_app

REPO = Path(__file__).resolve().parents[1]
TOOL_NAMES = [t["name"] for t in PRY_TOOLS]

# Assets verified live on 2026-10-18. Anything else in a manifest is a 404.
LIVE_ASSETS = {
    "https://pryscraper.com",
    "https://pryscraper.com/logo-mark-v2.png",
    "https://pryscraper.com/og.png",
    "https://docs.pryscraper.com",
    "https://api.pryscraper.com/mcp/",
    "https://git.rugmunch.io/RugMunchMedia/pryscraper",
    "https://pryscraper.com/schema.json",  # placeholder never shipped
}
DEAD_ASSETS = (
    "https://pryscraper.com/img/pry.png",
    "https://pryscraper.com/img/logo.svg",
)


def _manifest(name: str) -> dict[str, Any]:
    return json.loads((REPO / name).read_text(encoding="utf-8"))


# ── stdio transport ───────────────────────────────────────────────


def _spawn_stdio() -> subprocess.Popen[str]:
    env = dict(os.environ)
    env.setdefault("PRY_SECRET_BACKEND", "env")
    env.setdefault("PRY_API_KEY", "")
    env["PRY_API_URL"] = "http://127.0.0.1:1"  # never contacted during discovery
    return subprocess.Popen(
        [sys.executable, "-m", "pry.api.mcp_production"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )


def _stdio_requests() -> list[dict[str, Any]]:
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]


def _collect(proc: subprocess.Popen[str], count: int) -> dict[int, dict[str, Any]]:
    responses: dict[int, dict[str, Any]] = {}
    while len(responses) < count:
        line = (proc.stdout.readline() if proc.stdout else "").strip()
        if not line:
            pytest.fail(
                "stdio server closed the stream before answering: "
                + ((proc.stderr.read() if proc.stderr else "")[:500])
            )
        payload = json.loads(line)  # a banner here is a hard failure
        if "id" in payload:
            responses[payload["id"]] = payload
    return responses


def test_stdio_entrypoint_handshake() -> None:
    """`python -m pry.api.mcp_production` speaks MCP over stdio."""
    proc = _spawn_stdio()
    try:
        assert proc.stdin is not None
        for message in _stdio_requests():
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        responses = _collect(proc, 2)
        init = responses[1]["result"]
        assert init["serverInfo"]["name"] == "pry"
        assert "tools" in init["capabilities"]
        tools = responses[2]["result"]["tools"]
        assert [t["name"] for t in tools] == TOOL_NAMES, "stdio surface drifted"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()

# ── HTTP transport + auth ─────────────────────────────────────────


@pytest.fixture
def mcp_http() -> TestClient:
    return TestClient(create_mcp_app())


def test_http_health_reports_full_surface(mcp_http: TestClient) -> None:
    resp = mcp_http.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["tools_count"] == len(PRY_TOOLS) == 99
    assert "streamable-http" in body["transports"]


def test_http_initialize_and_tools_list(mcp_http: TestClient) -> None:
    init = mcp_http.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1"},
            },
        },
    )
    assert init.status_code == 200
    assert init.headers.get("mcp-session-id"), "initialize must issue a session id"
    assert init.json()["result"]["serverInfo"]["name"] == "pry"

    listed = mcp_http.post("/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed.status_code == 200
    tools = listed.json()["result"]["tools"]
    assert [t["name"] for t in tools] == TOOL_NAMES


def test_http_tools_call_requires_a_key(
    mcp_http: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tools/call is fail-closed; discovery methods stay public."""
    import pry.core.settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "api_key", "distribution-test-key", raising=False)
    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "pry_x402_pricing", "arguments": {}}}

    anonymous = mcp_http.post("/", json=call)
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == -32001

    wrong = mcp_http.post("/", json=call, headers={"authorization": "Bearer nope"})
    assert wrong.status_code == 401

    keyed = mcp_http.post(
        "/", json=call, headers={"authorization": "Bearer distribution-test-key"}
    )
    assert keyed.status_code != 401, "a valid Bearer key must pass the gate"


# ── manifests ─────────────────────────────────────────────────────


def test_server_json_is_schema_valid_and_matches_tools() -> None:
    doc = _manifest("server.json")
    # Fields the official registry requires.
    assert doc["name"] == "io.rugmunch/pry"
    assert doc["version"] == "3.0.0"
    assert 1 <= len(doc["description"]) <= 100, "registry caps description at 100 chars"
    assert doc["packages"][0]["registryType"] == "pypi"
    assert doc["packages"][0]["identifier"] == "pryscraper-mcp"
    assert doc["packages"][0]["transport"]["type"] == "stdio"
    assert doc["remotes"][0]["type"] == "streamable-http"
    assert doc["icons"][0]["src"] in LIVE_ASSETS
    assert [t["name"] for t in doc["tools"]] == TOOL_NAMES


def test_glama_manifest_matches_its_own_schema() -> None:
    doc = _manifest("glama.json")
    # Glama's published schema: https://glama.ai/mcp/schemas/server.json
    assert "maintainers" in doc
    assert isinstance(doc["maintainers"], list)
    assert [t["name"] for t in doc["tools"]] == TOOL_NAMES
    assert doc["transports"][0]["type"] == "stdio"


def test_pulsemcp_manifest_matches_tools() -> None:
    doc = _manifest("pulsemcp.json")
    assert doc["tools"] == TOOL_NAMES
    assert doc["install"]["command"] == "pryscraper-mcp"


def test_manifests_have_no_dead_or_foreign_urls() -> None:
    for name in ("server.json", "glama.json", "pulsemcp.json", "smithery.yaml",
                 "registry_submissions/mcp_listing.json",
                 "registry_submissions/x402_listing.json"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "codeberg" not in text.lower(), f"{name} points at a dead mirror"
        for dead in DEAD_ASSETS:
            assert dead not in text, f"{name} references a 404 asset: {dead}"


def test_smithery_config_runs_a_proven_module() -> None:
    text = (REPO / "smithery.yaml").read_text(encoding="utf-8")
    assert "python3" in text
    assert "-m" in text
    assert "pry.api.mcp_production" in text
    assert "type: stdio" in text
