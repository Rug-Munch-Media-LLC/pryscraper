# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Layer 1: tool metadata audit."""

from __future__ import annotations

import asyncio

import pytest

from pry_mcp import PRY_TOOLS
from pry_mcp.tools import PRY_TOOL_NAMES

from ._support import _server


class TestToolMetadata:
    """Every PRY_TOOLS entry must meet the 2026 MCP quality bar."""

    def test_tool_count_consistent(self) -> None:
        """PRY_TOOLS and PRY_TOOL_NAMES must be internally consistent.

        The absolute count is dynamic — it is derived from the registered
        tools in ``pry_mcp.tools.PRY_TOOLS`` rather than a hardcoded constant,
        so new tools (e.g. ``pry_kol_leaderboards``) don't break the audit.
        """
        registered = len(PRY_TOOLS)
        assert registered > 0
        assert registered == len(PRY_TOOL_NAMES)
        assert registered == len({t["name"] for t in PRY_TOOLS})
        assert all(t["name"] for t in PRY_TOOLS)

    @pytest.mark.parametrize("tool_name", sorted(PRY_TOOL_NAMES))
    def test_tools_list_metadata(self, tool_name: str) -> None:
        srv = _server()
        resp = asyncio.run(srv.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
        assert "error" not in resp
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        assert tool_name in tools, f"tools/list missing {tool_name}"
        tool = tools[tool_name]

        # (a) example-rich description: WHAT + WHEN + concrete example.
        desc = tool["description"]
        assert desc, f"{tool_name}: empty description"
        assert desc.strip(), f"{tool_name}: blank description"
        assert len(desc.split()) >= 20, (
            f"{tool_name}: description too thin ({len(desc.split())} words)"
        )
        assert any(
            marker in desc for marker in ("e.g.", "example", "Example", " like ", "such as")
        ), f"{tool_name}: description lacks a concrete example"

        # (b) complete inputSchema: object, every param typed + described,
        #     required flags reference real properties.
        schema = tool["inputSchema"]
        assert schema["type"] == "object", f"{tool_name}: inputSchema not object"
        props = schema["properties"]
        for pname, p in props.items():
            assert "type" in p, f"{tool_name}.{pname}: missing type"
            assert p.get("description"), f"{tool_name}.{pname}: missing description"
        for req in schema.get("required", []):
            assert req in props, f"{tool_name}: required {req} not in properties"

        # (c) outputSchema present.
        assert "outputSchema" in tool, f"{tool_name}: missing outputSchema"

        # (d) annotations triple present and coherent.
        ann = tool.get("annotations", {})
        for key in ("readOnlyHint", "destructiveHint", "idempotentHint"):
            assert key in ann, f"{tool_name}: missing annotation {key}"
        if tool_name == "pry_monitor":
            assert ann["readOnlyHint"] is False, "pry_monitor mutates server state"
            assert ann["idempotentHint"] is False, "pry_monitor creates a new monitor per call"
            assert ann["destructiveHint"] is False, "pry_monitor never deletes data"

    def test_state_mutating_tool_annotations(self) -> None:
        """Only pry_monitor may opt out of the read-only default."""
        for tool in PRY_TOOLS:
            if tool["name"] == "pry_monitor":
                continue
            ann = tool["annotations"]
            assert ann["readOnlyHint"] is True, f"{tool['name']} should be read-only"
            assert ann["destructiveHint"] is False, f"{tool['name']} should be non-destructive"
            assert ann["idempotentHint"] is True, f"{tool['name']} should be idempotent"
