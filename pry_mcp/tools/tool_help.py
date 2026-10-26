"""Pry — ``pry_help``: the grouped index a model reads instead of 100 schemas.

One tool, one job: return the surface grouped by task, with the canonical entry
first and every other tool listed under it with a one-line purpose. The index is
derived from ``PRY_TOOLS`` at call time, so a newly registered tool appears here
without a second edit.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from typing import Any

from pry_mcp.surface import CANONICAL, SPEND_TOOLS, group_of

PRY_HELP_TOOL: dict[str, Any] = {
    "name": "pry_help",
    "description": (
        "Grouped index of every Pry tool: task group, canonical entry point, one-line purpose, "
        "and which tools spend credits. Call this first instead of loading the full tool list. "
        "Pass group='search' (or scrape/extract/data/sports/crypto/...) to narrow. "
        "Always answers: never spends, never scrapes, no network."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "group": {
                "type": "string",
                "description": "Optional group filter, e.g. 'search', 'scrape', 'sports'.",
            },
            "verbose": {
                "type": "boolean",
                "description": "Include every tool description; default is one line per tool.",
                "default": False,
            },
        },
        "required": [],
    },
    "annotations": {
        "title": "Pry tool index",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}

PRY_TOOLS: list[dict[str, Any]] = [PRY_HELP_TOOL]


def _line(desc: str, limit: int) -> str:
    text = " ".join((desc or "").split())
    cut = text.split(". ")[0]
    return cut if len(cut) <= limit else cut[: limit - 1].rstrip() + "…"


def build_index(
    tools: list[dict[str, Any]], group: str | None = None, verbose: bool = False
) -> dict[str, Any]:
    """Build the grouped index payload from the registered tool definitions."""
    groups: dict[str, list[dict[str, Any]]] = {}
    spend: list[str] = []
    for tool in tools:
        name = tool["name"]
        g = group_of(name)
        if group and g != group:
            continue
        if name in SPEND_TOOLS:
            spend.append(name)
        groups.setdefault(g, []).append(
            {
                "tool": name,
                "purpose": _line(tool.get("description", ""), 400 if verbose else 110),
                "spends_credits": name in SPEND_TOOLS,
            }
        )
    return {
        "tool": "pry_help",
        "tool_count": len(tools),
        "groups": dict(sorted(groups.items())),
        "canonical": {k: list(v) for k, v in CANONICAL.items()},
        "spend_tools": sorted(spend),
        "note": (
            "One entry per task — search / scrape / extract / structure / data / help — "
            "listed under canonical; every other tool is grouped beneath it. "
            "Spend tools refuse without confirm_spend=true."
        ),
    }


async def call_help_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Execute ``pry_help``; return None for any other tool name."""
    if name != "pry_help":
        return None
    from pry_mcp.tools import PRY_TOOLS as ALL_TOOLS

    payload = build_index(
        ALL_TOOLS,
        group=arguments.get("group") or None,
        verbose=bool(arguments.get("verbose")),
    )
    return {"content": [{"type": "text", "text": __import__("json").dumps(payload)}]}
