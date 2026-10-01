"""Pry - MCP tool definitions: government + IP-data tools and dispatchers..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
from typing import Any

from ._common import (
    _data_module_unavailable,
    _missing_arg,
    _ModuleNotFound,
    resolve_domain_package,
)

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_procurement",
        "description": (
            "Search U.S. federal procurement opportunities and contract awards from the "
            "public SAM.gov data feed, returning title, agency, notice type, and deadline. "
            "Use to find government business opportunities for a capability, e.g. 'what "
            "cybersecurity contracts are open?'. The gov_data module is built in parallel; "
            "until it lands this tool returns a readable not-available message instead of "
            "erroring."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search, e.g. 'cybersecurity'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum results to return (default: 20)",
                },
            },
            "required": ["query"],
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
                            "notice_id": {"type": "string"},
                            "title": {"type": "string"},
                            "agency": {"type": "string"},
                            "notice_type": {"type": "string"},
                            "deadline": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_recalls",
        "description": (
            "Search recent product recalls from the U.S. CPSC public data feed, returning "
            "product name, hazard, recall date, and remedy. Use for consumer-safety "
            "monitoring or supply-chain due diligence, e.g. 'recent recalls for e-bike "
            "batteries'. The gov_data module is built in parallel; until it lands this "
            "tool returns a readable not-available message instead of erroring."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search, e.g. 'e-bike battery'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum results to return (default: 20)",
                },
            },
            "required": ["query"],
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
                            "recall_id": {"type": "string"},
                            "product": {"type": "string"},
                            "hazard": {"type": "string"},
                            "recall_date": {"type": "string"},
                            "remedy": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
]

PRY_IP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_patents",
        "description": (
            "Search U.S. patents by keyword using the USPTO public data feeds, returning "
            "patent number, title, assignee, and grant date. Use for IP landscaping or "
            "freedom-to-operate checks, e.g. 'patents for blockchain identity'. The ip_data "
            "module is built in parallel; until it lands this tool returns a readable "
            "not-available message instead of erroring."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search, e.g. 'blockchain identity'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum results to return (default: 20)",
                },
            },
            "required": ["query"],
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
                            "patent_number": {"type": "string"},
                            "title": {"type": "string"},
                            "assignee": {"type": "string"},
                            "grant_date": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_trademarks",
        "description": (
            "Search U.S. trademarks by keyword or owner using the USPTO public data feeds, "
            "returning serial number, mark text, owner, and status. Use for brand "
            "clearance before launching a product or token name, e.g. 'is RugMunch "
            "trademarked?'. The ip_data module is built in parallel; until it lands this "
            "tool returns a readable not-available message instead of erroring."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or owner search, e.g. 'RugMunch'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum results to return (default: 20)",
                },
            },
            "required": ["query"],
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
                            "serial_number": {"type": "string"},
                            "mark": {"type": "string"},
                            "owner": {"type": "string"},
                            "status": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
]

# Candidate public function names for the gov_data / ip_data packages. These
# packages land from parallel agents; the dispatcher resolves whichever name
# the landed module actually exposes, and reports "not available" otherwise.
_GOV_TOOL_FNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pry_procurement": (
        "gov_data",
        ("search_opportunities", "search_procurement", "list_procurement"),
    ),
    "pry_recalls": ("gov_data", ("search_recalls", "get_recalls", "list_recalls")),
}
_IP_TOOL_FNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pry_patents": ("ip_data", ("search_patents", "get_patents", "list_patents")),
    "pry_trademarks": ("ip_data", ("search_trademarks", "get_trademarks", "list_trademarks")),
}


async def _call_candidate_domain_tool(
    name: str,
    arguments: dict[str, Any],
    registry: dict[str, tuple[str, tuple[str, ...]]],
) -> dict[str, Any] | None:
    """Run a gov/ip tool via candidate function names with a guarded import."""
    entry = registry.get(name)
    if entry is None:
        return None
    package, candidates = entry
    query = arguments.get("query", "")
    if not query:
        return _missing_arg(name, "query")
    limit = int(arguments.get("limit", 20))
    try:
        # ``gov_data`` / ``ip_data`` are subpackages of the top-level
        # ``datasets`` namespace, so resolve the package the same way the
        # per-module dispatchers do rather than importing the bare name.
        mod = resolve_domain_package(package)
    except _ModuleNotFound:
        return _data_module_unavailable(name, package)
    fn = next((getattr(mod, cand, None) for cand in candidates if hasattr(mod, cand)), None)
    if fn is None:
        return _data_module_unavailable(name, package)
    data = await fn(query, limit=limit) if _candidate_takes_limit(fn) else await fn(query)
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"success": True, "data": data, "query": query}, indent=2),
            }
        ],
        "isError": False,
    }


def _candidate_takes_limit(fn: Any) -> bool:
    """Best-effort: does the gov/ip candidate accept a limit keyword?"""
    import inspect

    try:
        params = inspect.signature(fn).parameters
        return "limit" in params
    except (TypeError, ValueError):
        return True


async def call_gov_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch government-data MCP tools to their ``gov_data`` handlers (guarded)."""
    return await _call_candidate_domain_tool(name, arguments, _GOV_TOOL_FNS)


async def call_ip_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch IP-data MCP tools to their ``ip_data`` handlers (guarded)."""
    return await _call_candidate_domain_tool(name, arguments, _IP_TOOL_FNS)
