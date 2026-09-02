"""Pry - MCP tool definitions: travel tools and dispatcher..

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

from ._common import _data_module_unavailable, _missing_arg

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_flights_grid",
        "description": (
            "Get the cheapest flight option per day between two dates for an origin and "
            "destination pair, using Google Flights' public tfs deep-link page. Use to find "
            "the cheapest day to fly on a trip, e.g. 'what's the cheapest day JFK→CDG next "
            "month?'. Returns a per-day price grid; never raises and returns an empty grid "
            "when Google Flights blocks the scrape (embedded JSON drifts over time)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "IATA origin code, e.g. 'JFK'",
                },
                "dest": {
                    "type": "string",
                    "description": "IATA destination code, e.g. 'CDG'",
                },
                "start_date": {
                    "type": "string",
                    "description": "First date (YYYY-MM-DD), e.g. '2026-09-01'",
                },
                "end_date": {
                    "type": "string",
                    "description": "Last date (YYYY-MM-DD), e.g. '2026-09-30'",
                },
            },
            "required": ["origin", "dest", "start_date", "end_date"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "origin": {"type": "string"},
                        "dest": {"type": "string"},
                        "days": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "date": {"type": "string"},
                                    "price_usd": {"type": "number"},
                                    "airline": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_hotel_rates",
        "description": (
            "Get per-night hotel rates for a stay window from Google Hotels with a "
            "Booking.com fallback, both free and keyless page scrapes. Use to compare "
            "prices across sources for a specific property, e.g. 'what does the Ritz Paris "
            "cost for September 10-14?'. Returns per-night rate breakdowns; never raises "
            "and returns an empty object when neither source is reachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hotel_name": {
                    "type": "string",
                    "description": "Hotel name or location query, e.g. 'Ritz Paris'",
                },
                "checkin": {
                    "type": "string",
                    "description": "Check-in date (YYYY-MM-DD), e.g. '2026-09-10'",
                },
                "checkout": {
                    "type": "string",
                    "description": "Check-out date (YYYY-MM-DD), e.g. '2026-09-14'",
                },
            },
            "required": ["hotel_name", "checkin", "checkout"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "hotel": {"type": "string"},
                        "nights": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "date": {"type": "string"},
                                    "price_usd": {"type": "number"},
                                    "source": {"type": "string"},
                                },
                            },
                        },
                        "total_usd": {"type": "number"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]


async def call_travel_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch travel MCP tools to their ``travel`` handlers (guarded)."""
    if name == "pry_flights_grid":
        origin = arguments.get("origin", "")
        dest = arguments.get("dest", "")
        start_date = arguments.get("start_date", "")
        end_date = arguments.get("end_date", "")
        if not (origin and dest and start_date and end_date):
            return _missing_arg(name, "origin/dest/start_date/end_date")
        try:
            from travel.flights import cheapest_date_grid
        except ImportError:
            return _data_module_unavailable(name, "travel")
        data = await cheapest_date_grid(origin, dest, start_date, end_date)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": True,
                            "data": data,
                            "origin": origin.upper(),
                            "dest": dest.upper(),
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    if name == "pry_hotel_rates":
        hotel_name = arguments.get("hotel_name", "")
        checkin = arguments.get("checkin", "")
        checkout = arguments.get("checkout", "")
        if not (hotel_name and checkin and checkout):
            return _missing_arg(name, "hotel_name/checkin/checkout")
        try:
            from travel.hotels import get_hotel_rates
        except ImportError:
            return _data_module_unavailable(name, "travel")
        hotel_data = await get_hotel_rates(hotel_name, checkin, checkout)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": hotel_data}, indent=2),
                }
            ],
            "isError": False,
        }

    return None
