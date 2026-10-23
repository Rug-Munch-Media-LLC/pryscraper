"""Pry - MCP tool definitions: climate / agriculture tools and dispatcher..

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
from ._kwargs_climate_research import _domain_tool_kwargs

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_weather",
        "description": (
            "Get current weather and short-range forecasts for a location, built "
            "for research pipelines that need environmental context (rain, wind, "
            "temperature, AQI) alongside other data. "
            "Use to enrich scraping jobs or model outdoor conditions, e.g. "
            "'what is the weather in Austin, TX right now?' or call with "
            "latitude/longitude to avoid geocoding."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or place query, e.g. 'Austin, TX'",
                },
                "latitude": {
                    "type": "number",
                    "description": "Latitude (alternative to location)",
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude (alternative to location)",
                },
                "forecast_days": {
                    "type": "integer",
                    "default": 3,
                    "minimum": 0,
                    "maximum": 16,
                    "description": "Days of forecast to include (0 = current only)",
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "object",
                            "properties": {
                                "lat": {"type": "number"},
                                "lon": {"type": "number"},
                                "city": {"type": ["string", "null"]},
                                "state": {"type": ["string", "null"]},
                            },
                        },
                        "current": {
                            "type": "object",
                            "properties": {
                                "temp_f": {"type": ["number", "null"]},
                                "condition": {"type": ["string", "null"]},
                                "wind_mph": {"type": ["number", "null"]},
                                "humidity_pct": {"type": ["number", "null"]},
                                "observed_at": {"type": ["string", "null"]},
                            },
                        },
                        "forecast": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "date": {"type": "string"},
                                    "high_f": {"type": ["number", "null"]},
                                    "low_f": {"type": ["number", "null"]},
                                    "condition": {"type": ["string", "null"]},
                                    "precip_pct": {"type": ["number", "null"]},
                                },
                            },
                        },
                        "alerts": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_agri",
        "description": (
            "Get agricultural data: crop conditions, growing-degree days, soil "
            "moisture, and commodity-relevant climate indices for a region. "
            "Use to model crop yield risk or monitor growing regions, e.g. "
            "'what are the corn growing conditions in Iowa?' or call with "
            "region='us' and crop='corn' for the USDA-style condition report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "default": "us",
                    "description": "Region code, e.g. 'us', 'br', 'in' (default: 'us')",
                },
                "crop": {
                    "type": "string",
                    "default": "",
                    "description": "Crop filter, e.g. 'corn', 'soybeans', 'wheat'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of records (default: 20)",
                },
            },
            "required": [],
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
                            "commodity": {"type": "string"},
                            "state": {"type": "string"},
                            "year": {"type": "integer"},
                            "price": {"type": "number"},
                            "unit": {"type": "string"},
                            "short_desc": {"type": "string"},
                            "source": {"type": "string"},
                        },
                    },
                },
                "region": {"type": "string"},
            },
            "required": ["success"],
        },
    },
]

# ── Climate / research domains (parallel build, guarded) ───────────────
# Candidate public function names for the climate_data / research_data
# modules. These packages land from parallel agents; every import below is
# guarded so the dispatcher degrades gracefully (a readable message) if a
# module has not landed yet. Each tool maps to one or more
# (module, candidate-callables) options tried in order, so the dispatcher
# resolves whichever module/function the landed code actually exposes.
_CLIMATE_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_weather": (
        ("weather", ("get_forecast", "get_weather", "current_weather", "weather_now")),
    ),
    "pry_agri": (
        ("agri", ("get_crop_prices", "get_agri", "agri_report", "get_agriculture")),
        ("agriculture", ("get_crop_prices", "get_agri", "agri_report", "get_agriculture")),
    ),
}


async def call_climate_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch climate MCP tools to their ``climate_data`` handlers (guarded).

    The ``climate_data`` subpackage (weather, agri) is built in parallel by
    other agents; every import is guarded so this dispatcher degrades
    gracefully (a readable message) if a module has not landed yet. Returns
    ``None`` for non-climate tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name, arguments, "climate_data", _CLIMATE_TOOL_FNS, _domain_tool_kwargs
    )
