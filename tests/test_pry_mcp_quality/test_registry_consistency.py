# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Layer 4: tool-count consistency with registry files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from pry_mcp import PRY_TOOLS
from pry_mcp.tools import PRY_TOOL_NAMES

REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_tools_list(obj: Any) -> list[Any] | None:
    """Recursively find the first ``tools`` list in a registry JSON doc."""
    if isinstance(obj, dict):
        if "tools" in obj and isinstance(obj["tools"], list):
            return obj["tools"]
        for value in obj.values():
            found = _find_tools_list(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_tools_list(value)
            if found is not None:
                return found
    return None


class TestRegistryConsistency:
    """PRY_TOOLS must match every published registry file (currently 98)."""

    @pytest.mark.parametrize("fname", ["server.json", "glama.json", "pulsemcp.json"])
    def test_json_registries_match(self, fname: str) -> None:
        data = json.loads((REPO_ROOT / fname).read_text(encoding="utf-8"))
        tools = _find_tools_list(data)
        assert tools is not None, f"{fname}: no tools list found"
        if fname == "pulsemcp.json":
            names = {t for t in tools if isinstance(t, str)}
        else:
            names = {t["name"] for t in tools if isinstance(t, dict) and "name" in t}
        assert names == set(PRY_TOOL_NAMES), (
            f"{fname} drift: missing={sorted(set(PRY_TOOL_NAMES) - names)} "
            f"extra={sorted(names - set(PRY_TOOL_NAMES))}"
        )

    def test_llms_txt_lists_every_tool(self) -> None:
        text = (REPO_ROOT / "llms.txt").read_text(encoding="utf-8")
        # llms.txt lists each tool as a "### pry_tool_name" heading (not a
        # "- [pry_...]" bullet) — match the actual file format.
        listed = set(re.findall(r"^### (pry_[a-z0-9_]+)", text, flags=re.MULTILINE))
        assert listed == set(PRY_TOOL_NAMES), (
            f"llms.txt drift: missing={sorted(set(PRY_TOOL_NAMES) - listed)} "
            f"extra={sorted(listed - set(PRY_TOOL_NAMES))}"
        )

    def test_smithery_comment_matches_count(self) -> None:
        text = (REPO_ROOT / "smithery.yaml").read_text(encoding="utf-8")
        expected = f"Tool count: {len(PRY_TOOLS)}"
        match = re.search(r"Tool count: (\d+)", text)
        actual = match.group(1) if match else "?"
        assert expected in text, (
            f"smithery.yaml tool-count comment drifted: expected '{expected}', "
            f"file says 'Tool count: {actual}'"
        )
