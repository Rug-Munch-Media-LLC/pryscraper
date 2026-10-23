"""Pry - MCP tool definitions: events data tools (tickets, resale).

Split from the former ``pry_mcp/tools/data.py`` god file. Holds the
events-domain tool schemas (``PRY_TOOLS``), the guarded candidate registry
(``_EVENTS_TOOL_FNS``), and the ``call_events_tool`` dispatcher.
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
        "name": "pry_events",
        "description": (
            "Search live event listings (concerts, sports, theater) by keyword "
            "and optionally location or date, backed by Ticketmaster / SeatGeek "
            "class feeds. Use to find upcoming events for an artist or venue, "
            "e.g. 'what concerts are near Austin next month?' or call with "
            "query='Taylor Swift' and location='New York' for dated listings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Event keyword search, e.g. 'Taylor Swift' or 'Broadway'",
                },
                "location": {
                    "type": "string",
                    "description": "City / region filter, e.g. 'New York' (optional)",
                },
                "date": {
                    "type": "string",
                    "description": "Date filter YYYY-MM-DD (optional)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 200,
                    "description": "Maximum number of events (default: 20)",
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
                            "event_id": {"type": "string"},
                            "name": {"type": "string"},
                            "venue": {"type": "string"},
                            "city": {"type": "string"},
                            "date": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_resale",
        "description": (
            "Get resale ticket pricing for a specific event: asking prices, "
            "ticket counts, and section-level ranges across resale "
            "marketplaces. Use with an event_id from pry_events to size demand "
            "before buying, e.g. call with event_id from a sold-out concert to "
            "see floor and nosebleed asking ranges side by side."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Event identifier from pry_events, e.g. 'vv1aZt7B8v'",
                },
            },
            "required": ["event_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "min_price": {"type": "number"},
                        "max_price": {"type": "number"},
                        "ticket_count": {"type": "integer"},
                        "sections": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
]

# ── Events candidate registry (guarded) ───────────────────────────────
# Candidate public function names for the events_data package (``tickets``).
# These land from parallel agents; every import is guarded so the dispatcher
# degrades gracefully (a readable message) if a module has not landed yet.
_EVENTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_events": (("tickets", ("search_events", "find_events", "get_events", "events")),),
    "pry_resale": (("tickets", ("get_resale_prices", "resale_prices", "get_resale")),),
}


async def call_events_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch events-data MCP tools to their ``events_data`` handlers (guarded).

    The ``events_data`` subpackage (``tickets``) is built in parallel by other
    agents; every import is guarded so this dispatcher degrades gracefully (a
    readable message) if a module has not landed yet. Returns ``None`` for
    non-events tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "events_data",
        _EVENTS_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_events": "query", "pry_resale": "event_id"},
    )
