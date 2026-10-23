"""Pry - MCP tool definitions: events / freight / energy / food / supply data tools and dispatchers.

Thin re-export module that aggregates the split data-domain tool modules
(``data_events``, ``data_freight``, ``data_energy``, ``data_food``,
``data_supply``) and preserves the former monolithic ``pry_mcp/tools/data.py``
public API: the merged ``PRY_TOOLS`` registry, the per-domain candidate
registries (``_EVENTS_TOOL_FNS`` ... ``_SUPPLY_TOOL_FNS``), the shared
``_broad_domain_tool_kwargs`` builder, and the guarded ``call_*_tool``
dispatchers.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import logging
from typing import Any

from ._kwargs_data import _broad_domain_tool_kwargs
from .data_energy import _ENERGY_TOOL_FNS, PRY_TOOLS as _ENERGY_TOOLS, call_energy_tool
from .data_events import _EVENTS_TOOL_FNS, PRY_TOOLS as _EVENTS_TOOLS, call_events_tool
from .data_food import _FOOD_TOOL_FNS, PRY_TOOLS as _FOOD_TOOLS, call_food_tool
from .data_freight import _FREIGHT_TOOL_FNS, PRY_TOOLS as _FREIGHT_TOOLS, call_freight_tool
from .data_supply import _SUPPLY_TOOL_FNS, PRY_TOOLS as _SUPPLY_TOOLS, call_supply_tool

logger = logging.getLogger(__name__)

# Merge the per-domain tool lists, preserving the exact tool order of the
# former monolithic data.py PRY_TOOLS list:
#   events, resale, freight, energy_lmp, grocery, restaurant, imports, firmographics
PRY_TOOLS: list[dict[str, Any]] = [
    *_EVENTS_TOOLS,
    *_FREIGHT_TOOLS,
    *_ENERGY_TOOLS,
    *_FOOD_TOOLS,
    *_SUPPLY_TOOLS,
]




__all__ = [
    "PRY_TOOLS",
    "_ENERGY_TOOL_FNS",
    "_EVENTS_TOOL_FNS",
    "_FOOD_TOOL_FNS",
    "_FREIGHT_TOOL_FNS",
    "_SUPPLY_TOOL_FNS",
    "_broad_domain_tool_kwargs",
    "call_energy_tool",
    "call_events_tool",
    "call_food_tool",
    "call_freight_tool",
    "call_supply_tool",
]
