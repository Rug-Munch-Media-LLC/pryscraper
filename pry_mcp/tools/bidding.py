"""Pry - MCP tool definitions: contracts / grants tools and dispatcher..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from ._common import _call_domain_dispatcher
from ._kwargs_new_domains import _new_domain_tool_kwargs

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_contracts",
        "description": (
            "Search government contract opportunities and awards by keyword across "
            "public procurement feeds, returning agency, solicitation number, award "
            "value, status, and deadline for each result. "
            "Use to monitor public-sector RFPs and awarded contracts, e.g. "
            "query='cybersecurity' for current federal bidding data. Best-effort over "
            "free public sources; never raises and returns an empty list on failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Contract search keywords, e.g. 'cybersecurity'",
                },
                "agency": {
                    "type": "string",
                    "description": "Optional agency filter, e.g. 'DHS'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of contracts to return (default: 20)",
                },
            },
            "required": ["query"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "agency": {"type": "string"},
                                    "solicitation_number": {"type": "string"},
                                    "value": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "status": {"type": "string"},
                                    "deadline": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "query": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_grants",
        "description": (
            "Search government grant opportunities by keyword across public grant "
            "feeds, returning agency, opportunity number, funding amount, eligibility, "
            "and deadline for each result. "
            "Use to find open funding programs for research, nonprofits, or "
            "businesses, e.g. query='small business innovation research'. Best-effort "
            "over free public sources; never raises and returns an empty list on failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Grant search keywords, e.g. 'small business innovation research'",
                },
                "agency": {
                    "type": "string",
                    "description": "Optional agency filter, e.g. 'NSF'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of grants to return (default: 20)",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of grants to skip before the page (pagination)",
                },
            },
            "required": ["query"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "agency": {"type": "string"},
                                    "opportunity_number": {"type": "string"},
                                    "amount": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "eligibility": {"type": "string"},
                                    "deadline": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "query": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]

# Candidate public function names for the bidding-data package
# (bidding_data.contracts, bidding_data.grants). The package lands from a
# parallel agent; every import below is guarded so the dispatchers degrade
# gracefully (a readable message) if a module has not landed yet. Mirrors the
# app-store / news / compliance / deals pattern.
_BIDDING_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_contracts": (
        ("contracts", ("search_contracts", "get_contracts", "contracts_search", "find_contracts")),
    ),
    "pry_grants": (("grants", ("search_grants", "get_grants", "grants_search", "find_grants")),),
}


async def call_bidding_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch bidding-data MCP tools to their ``bidding_data`` handlers (guarded).

    The ``bidding_data`` subpackage (``contracts``, ``grants``) is built in
    parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-bidding tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "bidding_data",
        _BIDDING_TOOL_FNS,
        _new_domain_tool_kwargs,
        required_args={"pry_contracts": "query", "pry_grants": "query"},
    )
