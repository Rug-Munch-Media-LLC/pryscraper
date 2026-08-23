# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP tool-surface integrity tests.

Pry exposes 71 MCP tools; every one must satisfy the same contract so AI
agents get a predictable surface:

- unique, well-named tools
- non-empty descriptions (agents choose tools by description)
- inputSchema is a JSON-Schema object whose `required` entries all exist
  in `properties`
- list_tools() projects PRY_TOOLS faithfully
"""

from __future__ import annotations

import re

import pytest

from pry_mcp.tools import PRY_TOOLS

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class TestToolSchemaIntegrity:
    def test_surface_is_large(self) -> None:
        assert len(PRY_TOOLS) >= 70

    def test_names_unique_and_well_formed(self) -> None:
        names = [t["name"] for t in PRY_TOOLS]
        assert len(names) == len(set(names)), "duplicate tool names"
        bad = [n for n in names if not NAME_RE.match(n)]
        assert not bad, f"malformed tool names: {bad}"

    def test_every_tool_has_description(self) -> None:
        thin = [t["name"] for t in PRY_TOOLS if len(t.get("description", "").strip()) < 20]
        assert not thin, f"tools with missing/thin descriptions: {thin[:10]}"

    def test_input_schema_is_object_with_properties(self) -> None:
        broken = []
        for t in PRY_TOOLS:
            schema = t.get("inputSchema")
            if not isinstance(schema, dict) or schema.get("type") != "object":
                broken.append((t["name"], "inputSchema not an object schema"))
                continue
            if not isinstance(schema.get("properties"), dict):
                broken.append((t["name"], "properties missing"))
        assert not broken, broken[:10]

    def test_required_subset_of_properties(self) -> None:
        """A required field absent from properties breaks client validation."""
        broken = []
        for t in PRY_TOOLS:
            schema = t.get("inputSchema", {})
            props = set(schema.get("properties", {}))
            for req in schema.get("required", []):
                if req not in props:
                    broken.append((t["name"], req))
        assert not broken, broken[:10]

    def test_urls_fields_documented_as_strings(self) -> None:
        """url-typed inputs must be string type (arrays of sources are
        expressed per-tool, never as bare objects)."""
        broken = []
        for t in PRY_TOOLS:
            for pname, prop in t.get("inputSchema", {}).get("properties", {}).items():
                if pname.endswith("url") and prop.get("type") not in ("string", "array"):
                    broken.append((t["name"], pname))
        assert not broken, broken[:10]


class TestListToolsProjection:
    @pytest.mark.asyncio
    async def test_list_tools_projects_all_entries(self) -> None:
        """Production runs the fallback server under MCP SDK >=2.0
        (sdk_server raises AttributeError there by design)."""
        from pry_mcp.fallback_server import make_fallback_server
        from pry_mcp.tools import PRY_TOOLS

        server = make_fallback_server()
        for entry in PRY_TOOLS:
            server.register_tool(entry["name"], entry)
        result = server.list_tools()  # sync dict: {"tools": [dict, ...]}
        tools = {t["name"]: t for t in result["tools"]}
        assert set(tools) == {e["name"] for e in PRY_TOOLS}
        for entry in PRY_TOOLS:
            projected = tools[entry["name"]]
            assert projected.get("description") == entry.get("description", "")
            assert projected.get("inputSchema", {}).get("type") == "object"
