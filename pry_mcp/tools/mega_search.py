"""Pry - MCP tool definition: consensus web search across every engine.

Returns a merged SERP. Every engine is queried concurrently and hits are
ranked by how many engines independently surfaced them, so the answer is
stronger than any single provider can give. Backed by
:mod:`pry.engine.mega_search`.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

PRY_MEGA_SEARCH_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_mega_search",
        "description": (
            "Search the web with EVERY engine at once and return one consensus-ranked "
            "list. Six independent engines (SearXNG, DuckDuckGo, Mojeek, Seznam, Yahoo, "
            "Qwant) are queried in parallel, results are deduplicated, and each hit is "
            "ranked by how many engines independently found it - so a link four engines "
            "agree on outranks a link only one returned. Use this when you want the best "
            "possible answer to a factual question and do not need page bodies; for "
            "full-page reading use pry_search instead. Results carry 'consensus' (engine "
            "count) and 'sources'; engines_ok / engines_failed show which legs answered."
            "For example, pry_mega_search(query='best rust web frameworks 2026', "
            "num_results=10) returns one deduplicated list where every result reports "
            "how many engines found it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms."},
                "num_results": {
                    "type": "integer",
                    "description": "How many merged results to return (default 10).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Result URL."},
                            "title": {"type": "string", "description": "Result title."},
                            "snippet": {"type": "string", "description": "Result snippet."},
                            "consensus": {
                                "type": "integer",
                                "description": "How many engines surfaced this URL.",
                            },
                            "sources": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Which engines found it.",
                            },
                        },
                    },
                },
                "total": {
                    "type": "integer",
                    "description": "Unique results before the limit.",
                },
                "query": {"type": "string", "description": "The query that was run."},
                "engines": {"description": "Per-engine status detail."},
                "engines_ok": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Engines that returned results.",
                },
                "engines_failed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Engines that returned nothing this run.",
                },
            },
            "required": ["results"],
        },
    }
]

_TOOL_FNS = {"pry_mega_search": "mega_search"}


def _kwargs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Map MCP arguments onto :func:`pry.engine.mega_search.mega_search`."""
    return {
        "query": str(arguments.get("query") or ""),
        "num_results": int(arguments.get("num_results") or 10),
    }


async def call_mega_search_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Dispatch ``pry_mega_search`` to the consensus engine.

    Returns ``None`` for other tool names so callers fall through, and a
    readable error if the engine has not landed.
    """
    if name not in _TOOL_FNS:
        return None
    try:
        from pry.engine.mega_search import mega_search
    except Exception as exc:  # noqa: BLE001 - degrade, never crash the server
        logger.warning(
            "suppressed %s in call_mega_search_tool (mega_search.py:121): %s",
            "Exception",
            exc,
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "error": (
                                f"Tool {name} is not available yet: the consensus search "
                                f"engine could not be imported ({exc})."
                            ),
                            "code": "MODULE_UNAVAILABLE",
                        }
                    ),
                }
            ],
            "isError": False,
        }
    return await mega_search(**_kwargs(arguments))


__all__ = ["PRY_MEGA_SEARCH_TOOLS", "call_mega_search_tool"]
