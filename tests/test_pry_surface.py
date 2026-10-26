# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""The canonical MCP surface: one entry per task, a spend gate, a deadline bound."""

from __future__ import annotations

import asyncio
import json

from pry_mcp import PRY_TOOLS
from pry_mcp.surface import ALIASES, CANONICAL, SEARCH_TOOLS, SPEND_TOOLS, gate, group_of
from pry_mcp.tools.tool_help import PRY_TOOLS as HELP_TOOLS, build_index

NAMES = [t["name"] for t in PRY_TOOLS]


def test_help_is_registered_once() -> None:
    assert [t["name"] for t in HELP_TOOLS] == ["pry_help"]
    assert NAMES.count("pry_help") == 1
    assert len(NAMES) == len(set(NAMES)), "tool names must stay unique"


def test_every_canonical_entry_is_a_registered_tool() -> None:
    named = [t for entries in CANONICAL.values() for t in entries]
    for tool in named + list(ALIASES):
        assert tool in NAMES, f"canonical/alias {tool} is not registered"


def test_index_covers_every_tool_exactly_once() -> None:
    payload = build_index(PRY_TOOLS)
    listed = [row["tool"] for rows in payload["groups"].values() for row in rows]
    assert sorted(listed) == sorted(NAMES)
    assert payload["tool_count"] == len(NAMES)


def test_groups_are_stable_and_small() -> None:
    assert group_of("pry_search_templates") == "search"
    assert group_of("pry_scrape") == "scrape"
    assert group_of("pry_odds") == "sports"
    assert group_of("pry_balance") == "billing"
    assert len(build_index(PRY_TOOLS)["groups"]) <= 15


def test_group_filter_narrows() -> None:
    payload = build_index(PRY_TOOLS, group="scrape")
    assert set(payload["groups"]) == {"scrape"}
    assert any(r["tool"] == "pry_scrape" for r in payload["groups"]["scrape"])


def test_spend_tool_blocks_without_the_flag() -> None:
    for name in sorted(SPEND_TOOLS):
        blocked = gate(name, {})
        assert blocked is not None
        assert blocked["error"]["code"] == "blocked.balance"
        assert json.loads(blocked["content"][0]["text"])["blocked"]["code"] == "blocked.balance"


def test_spend_tool_passes_with_the_flag() -> None:
    for name in sorted(SPEND_TOOLS):
        assert gate(name, {"confirm_spend": True}) is None


def test_free_tool_never_gates() -> None:
    assert gate("pry_balance", {}) is None
    assert gate("pry_scrape", {}) is None


def test_search_returns_partial_instead_of_blocking() -> None:
    async def slow(name, arguments, identity=None):
        await asyncio.sleep(5)
        return {"content": []}

    from pry_mcp.surface import surf_gate

    result = asyncio.run(surf_gate("pry_mega_search", {"max_ms": 50}, slow))
    payload = json.loads(result["content"][0]["text"])
    assert payload["partial"] is True
    assert payload["reason"] == "deadline_exceeded"
    assert payload["max_ms"] == 50


def test_search_names_are_registered() -> None:
    for name in sorted(SEARCH_TOOLS):
        assert name in NAMES, f"{name} is bounded but not registered"
