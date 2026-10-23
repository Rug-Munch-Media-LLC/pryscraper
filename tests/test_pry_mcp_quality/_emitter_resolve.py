# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Which module can put each PRY tool's payload on the wire.

The 2026-10-23 alignment fixed 20 schemas by hand. A curated table cannot hold
the rest — a new tool lands in one of three dispatch styles and nobody updates
it, so the phantom-field check silently stops covering that tool. The mapping is
derived from source instead (``_emitter_tools`` for guarded local dispatch,
``_emitter_routes`` for REST fallbacks) and this module merges the two.

``UNTRACKED`` names the tools that resolve to nothing. Each entry is a decision,
not an omission: a tool whose payload the MCP layer assembles inline, or whose
domain package has not landed. A tool that appears there by accident fails
``test_every_tool_resolves``, which is the point — the guard cannot silently
lose coverage.
"""

from __future__ import annotations

import functools
from typing import Any

from ._emitter_routes import tool_route_modules
from ._emitter_tools import tool_local_modules

#: Tools with no domain emitter to check, and why. Deliberately a decision
#: ledger rather than a skip list: ``test_untracked_*`` fails on an entry that
#: names a tool that no longer exists, one the resolver now reaches, or one
#: whose reason is too thin to review. Empty-but-explained is the goal.
UNTRACKED: dict[str, str] = {
    "pry_mega_search": (
        "fans out over the other tools and returns their combined items; "
        "it owns no domain module and declares no data shape"
    ),
}


@functools.cache
def tool_emitter_modules() -> dict[str, tuple[str, ...]]:
    """Tool name -> every module its payload can come from (sorted, unique)."""
    merged: dict[str, set[str]] = {}
    for source in (tool_local_modules(), tool_route_modules()):
        for tool, modules in source.items():
            merged.setdefault(tool, set()).update(modules)
    return {tool: tuple(sorted(modules)) for tool, modules in sorted(merged.items()) if modules}


def declared_data_fields(schema: dict[str, Any]) -> set[str]:
    """Every field name declared anywhere under the ``data`` property."""
    return _fields((schema.get("properties") or {}).get("data"))


def _fields(node: Any) -> set[str]:
    if isinstance(node, dict) and isinstance(node.get("items"), dict):
        node = node["items"]
    if not isinstance(node, dict):
        return set()
    names: set[str] = set(node.get("properties") or {})
    for sub in (node.get("properties") or {}).values():
        names |= _fields(sub)
    if isinstance(node.get("additionalProperties"), dict):
        names |= _fields(node["additionalProperties"])
    return names
