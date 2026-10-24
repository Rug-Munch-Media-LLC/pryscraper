"""Pry - MCP tool definitions: freight data tools (container rates).

Split from the former ``pry_mcp/tools/data.py`` god file. Holds the
freight-domain tool schemas (``PRY_TOOLS``), the guarded candidate registry
(``_FREIGHT_TOOL_FNS``), and the ``call_freight_tool`` dispatcher.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from ._common import _call_domain_dispatcher
from ._kwargs_data import _broad_domain_tool_kwargs

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_freight",
        "description": (
            "Get ocean container freight rates for a route: spot and contract "
            "rates per 40ft container across major trade lanes, plus FMC "
            "contract visibility where available. Use to model shipping costs, "
            "e.g. 'container rates from Shanghai to Los Angeles this week', or "
            "call with route='Far East to US West Coast' for the lane spread."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "route": {
                    "type": "string",
                    "description": (
                        "Trade lane, e.g. 'Shanghai to Los Angeles' or 'Far East to US West Coast'"
                    ),
                },
                "origin": {
                    "type": "string",
                    "description": "Origin port or region (alternative to route)",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination port or region (alternative to route)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of rate quotes (default: 20)",
                },
            },
            "required": ["route"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "route": {"type": "string"},
                            "origin": {"type": "string"},
                            "destination": {"type": "string"},
                            "rate_40ft_usd": {"type": "number"},
                            "index_source": {"type": "string"},
                            "date": {"type": "string"},
                        },
                    },
                },
                "route": {"type": "string"},
            },
            "required": ["success"],
        },
    },
]

# ── Freight candidate registry (guarded) ──────────────────────────────
# Candidate public function names for the freight_data package (``rates``).
# These land from parallel agents; every import is guarded so the dispatcher
# degrades gracefully (a readable message) if a module has not landed yet.
_FREIGHT_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_freight": (("rates", ("get_container_rates", "get_fmc_contracts", "container_rates")),),
}


async def call_freight_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch freight-data MCP tools to their ``freight_data`` handlers (guarded).

    The ``freight_data`` subpackage (``rates``) is built in parallel by other
    agents; every import is guarded so this dispatcher degrades gracefully (a
    readable message) if a module has not landed yet. Returns ``None`` for
    non-freight tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "freight_data",
        _FREIGHT_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_freight": "route"},
    )
