"""Pry - MCP tool definitions: kwargs builders for climate / research domains.

Extracted from ``_common.py`` to keep the core utilities focused.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _domain_module_unavailable(tool_name: str, package: str) -> dict[str, Any]:
    """MCP content dict for a climate/research tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the {package} module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
                ),
            }
        ],
        "isError": False,
    }


def _domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for a climate/research tool from MCP arguments.

    Mirrors ``_sports_tool_kwargs``: kwargs the landed callable does not
    support are filtered out by the dispatcher (``_callable_accepts``) so the
    call never fails on an unknown keyword.
    """
    if name == "pry_weather":
        kwargs: dict[str, Any] = {"location": arguments.get("location", "")}
        if arguments.get("latitude") is not None and arguments.get("longitude") is not None:
            kwargs["lat"] = float(arguments["latitude"])
            kwargs["lon"] = float(arguments["longitude"])
        if arguments.get("forecast_days") is not None:
            kwargs["days"] = int(arguments["forecast_days"])
        return kwargs
    if name == "pry_agri":
        return {
            "commodity": arguments.get("crop", "") or arguments.get("commodity", ""),
            "state": arguments.get("region", "all") or arguments.get("state", "all"),
            "limit": int(arguments.get("limit", 20)),
        }
    if name == "pry_papers":
        kwargs = {"query": arguments.get("query", ""), "limit": int(arguments.get("limit", 20))}
        if arguments.get("author"):
            kwargs["author"] = arguments["author"]
        if arguments.get("year_from") is not None:
            kwargs["year_from"] = int(arguments["year_from"])
        return kwargs
    if name == "pry_domain":
        kwargs = {"domain": arguments.get("domain", "")}
        if arguments.get("include_tech") is not None:
            kwargs["include_tech"] = bool(arguments["include_tech"])
        return kwargs
    return dict(arguments)
