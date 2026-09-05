"""Pry - MCP tool definitions: energy data tools (LMP prices).

Split from the former ``pry_mcp/tools/data.py`` god file. Holds the
energy-domain tool schemas (``PRY_TOOLS``), the guarded candidate registry
(``_ENERGY_TOOL_FNS``), and the ``call_energy_tool`` dispatcher.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from ._common import _broad_domain_tool_kwargs, _call_domain_dispatcher

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_energy_lmp",
        "description": (
            "Get electricity locational marginal prices (LMP) for an ISO region "
            "and date, with day-ahead / real-time splits where available. Use "
            "to model energy costs or spot volatility, e.g. 'LMP for ERCOT "
            "today', or call with region='PJM' and date='2026-08-16' for nodal "
            "pricing snapshots."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": (
                        "ISO / balancing authority, e.g. 'ERCOT', 'PJM', 'CAISO', 'NYISO'"
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "Date YYYY-MM-DD (default: today)",
                },
            },
            "required": ["region"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string"},
                        "date": {"type": "string"},
                        "lmp_usd_mwh": {"type": "number"},
                        "day_ahead_usd_mwh": {"type": "number"},
                        "real_time_usd_mwh": {"type": "number"},
                        "nodes": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
]

# ── Energy candidate registry (guarded) ───────────────────────────────
# Candidate public function names for the energy_data package (``lmp``).
# These land from parallel agents; every import is guarded so the dispatcher
# degrades gracefully (a readable message) if a module has not landed yet.
_ENERGY_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_energy_lmp": (
        (
            "lmp",
            (
                "get_lmp",
                "get_lmp_prices",
                "lmp_prices",
                "get_fuel_prices",
                "fuel_prices",
            ),
        ),
    ),
}


async def call_energy_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch energy-data MCP tools to their ``energy_data`` handlers (guarded).

    The ``energy_data`` subpackage (``lmp``) is built in parallel by other
    agents; every import is guarded so this dispatcher degrades gracefully (a
    readable message) if a module has not landed yet. Returns ``None`` for
    non-energy tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "energy_data",
        _ENERGY_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_energy_lmp": "region"},
    )
