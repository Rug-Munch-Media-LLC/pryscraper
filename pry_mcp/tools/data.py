"""Pry - MCP tool definitions: events / freight / energy / food / supply data tools and dispatchers..

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
                            "container_type": {"type": "string"},
                            "rate_usd": {"type": "number"},
                            "valid_from": {"type": "string"},
                            "valid_to": {"type": "string"},
                        },
                    },
                },
                "route": {"type": "string"},
            },
            "required": ["success"],
        },
    },
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
    {
        "name": "pry_grocery",
        "description": (
            "Get grocery prices for a product or category, optionally filtered "
            "by ZIP code for local store pricing. Use to compare staple costs "
            "across markets, e.g. 'price of a dozen eggs in 10001', or call "
            "with query='milk' and zip='78701' to see regional averages and "
            "store-level ranges."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Item or category, e.g. 'eggs', 'milk', 'avocados'",
                },
                "zip": {
                    "type": "string",
                    "description": "5-digit ZIP code for local pricing (optional)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of price records (default: 20)",
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
                            "item": {"type": "string"},
                            "price_usd": {"type": "number"},
                            "unit": {"type": "string"},
                            "store": {"type": "string"},
                            "zip": {"type": "string"},
                            "date": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_restaurant",
        "description": (
            "Get a restaurant's menu with prices: items, sections, and per-dish "
            "pricing for a named restaurant. Use to build cost-of-dining "
            "datasets or research competitors, e.g. call with "
            "name=\"Katz's Delicatessen\" and location='New York' for the full "
            "menu with prices."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": 'Restaurant name, e.g. "Katz\'s Delicatessen"',
                },
                "location": {
                    "type": "string",
                    "description": "City / address to disambiguate (optional)",
                },
            },
            "required": ["name"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "cuisine": {"type": "string"},
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "section": {"type": "string"},
                                    "items": {"type": "array", "items": {"type": "object"}},
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
        "name": "pry_imports",
        "description": (
            "Get U.S. customs import records for a company: shipment dates, "
            "commodity descriptions, suppliers, and origin countries. Use to "
            "size a competitor's supply chain or vet suppliers, e.g. call with "
            "company='Tesla Inc' for recent bill-of-lading entries with "
            "quantities."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name or importer-of-record, e.g. 'Tesla Inc'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of shipment records (default: 20)",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of shipment records to skip before the page (pagination)",
                },
            },
            "required": ["company"],
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
                            "consignee": {"type": "string"},
                            "supplier": {"type": "string"},
                            "commodity": {"type": "string"},
                            "origin_country": {"type": "string"},
                            "arrival_date": {"type": "string"},
                            "value_usd": {"type": "number"},
                        },
                    },
                },
                "company": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_firmographics",
        "description": (
            "Get firmographic data for a company: employee count band, revenue "
            "range, founding year, headquarters, industry, and company type. "
            "Use to segment leads or enrich CRM records, e.g. call with "
            "company='Rug Munch Media' for the standard firmographic profile "
            "with confidence scores."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name, e.g. 'Rug Munch Media'",
                },
            },
            "required": ["company"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"},
                        "employees_band": {"type": "string"},
                        "revenue_range_usd": {"type": "string"},
                        "founded_year": {"type": "integer"},
                        "headquarters": {"type": "string"},
                        "industry": {"type": "string"},
                        "company_type": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]

# ── Events / freight / energy / food / supply domains (parallel build) ──
# Candidate public function names for the five new data-domain packages
# (events_data, freight_data, energy_data, food_data, supply_data). These
# packages land from parallel agents; every import below is guarded so the
# dispatchers degrade gracefully (a readable message) if a module has not
# landed yet. Each tool maps to one or more (module, candidate-callables)
# options tried in order, mirroring the sports/climate pattern.
_EVENTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_events": (("tickets", ("search_events", "find_events", "get_events", "events")),),
    "pry_resale": (("tickets", ("get_resale_prices", "resale_prices", "get_resale")),),
}

_FREIGHT_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_freight": (("rates", ("get_container_rates", "get_fmc_contracts", "container_rates")),),
}

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

_FOOD_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_grocery": (("grocery", ("get_grocery_prices", "grocery_prices", "get_prices")),),
    "pry_restaurant": (("restaurants", ("get_restaurant_menu", "restaurant_menu", "get_menu")),),
}

_SUPPLY_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_imports": (("imports", ("get_import_records", "import_records", "get_imports")),),
    "pry_firmographics": (
        (
            "firmographics",
            (
                "get_company_firmographics",
                "company_firmographics",
                "get_firmographics",
            ),
        ),
    ),
}


def _broad_domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for an events/freight/energy/food/supply tool.

    Mirrors ``_domain_tool_kwargs`` / ``_sports_tool_kwargs``: kwargs the
    landed callable does not support are filtered out by the dispatcher
    (``_callable_accepts``) so the call never fails on an unknown keyword.
    """
    if name == "pry_events":
        return {
            "query": arguments.get("query", ""),
            "limit": int(arguments.get("limit", 20)),
        }
    if name == "pry_resale":
        return {"event_id": arguments.get("event_id", "")}
    if name == "pry_freight":
        kwargs: dict[str, Any] = {"route": arguments.get("route", "")}
        if arguments.get("origin"):
            kwargs["origin"] = arguments["origin"]
        if arguments.get("destination"):
            kwargs["destination"] = arguments["destination"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_energy_lmp":
        kwargs = {"region": arguments.get("region", "") or arguments.get("region_id", "")}
        if arguments.get("date"):
            kwargs["date"] = arguments["date"]
        return kwargs
    if name == "pry_grocery":
        kwargs = {"query": arguments.get("query", "") or arguments.get("item", "")}
        if arguments.get("zip"):
            kwargs["zip"] = arguments["zip"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_restaurant":
        kwargs = {"name": arguments.get("name", "")}
        if arguments.get("location"):
            kwargs["location"] = arguments["location"]
        return kwargs
    if name == "pry_imports":
        kwargs = {"company": arguments.get("company", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_firmographics":
        return {"company": arguments.get("company", "")}
    return dict(arguments)


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


async def call_food_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch food-data MCP tools to their ``food_data`` handlers (guarded).

    The ``food_data`` subpackage (``grocery``, ``restaurants``) is built in
    parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-food tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "food_data",
        _FOOD_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_grocery": "query", "pry_restaurant": "name"},
    )


async def call_supply_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch supply-data MCP tools to their ``supply_data`` handlers (guarded).

    The ``supply_data`` subpackage (``imports``, ``firmographics``) is built
    in parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-supply tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "supply_data",
        _SUPPLY_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_imports": "company", "pry_firmographics": "company"},
    )
