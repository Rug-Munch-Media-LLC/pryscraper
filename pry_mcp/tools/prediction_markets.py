"""Pry - MCP tool definitions: prediction-market tools (Polymarket, Kalshi).

Holds the prediction-market tool schemas (``PRY_TOOLS``) and the guarded
candidate registry (``_PREDICTION_TOOL_FNS``) for the
``datasets.prediction_markets`` package: live market listings merged
across Polymarket (Gamma API) and Kalshi (public trade API v2), plus
single-market detail lookup.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_prediction_markets",
        "description": (
            "Get live prediction-market data merged from Polymarket (Gamma API) "
            "and Kalshi (public trade API v2) — no API keys required. Each record "
            "includes the market question, binary outcomes with 0-1 probability "
            "prices (yes/no), 24h volume, liquidity, resolution/close date, and "
            "category. Use to gauge crowd consensus on future events, compare "
            "implied probabilities across platforms for arbitrage, or power "
            "event-probability widgets, e.g. 'what are the top crypto prediction "
            "markets right now?' or call with category='politics' to see election "
            "markets. Results are sorted by volume; both sources degrade "
            "independently, so a partial outage still returns the reachable side."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Category filter: sports, politics, crypto, economics, "
                        "or 'all' (default). Matched against market category "
                        "and question text"
                    ),
                },
                "source": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Data source: polymarket, kalshi, or 'all' (default, merges both)"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": ("Maximum number of market records (default: 20)"),
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
                            "market_id": {"type": "string"},
                            "source": {"type": "string"},
                            "question": {"type": "string"},
                            "category": {"type": ["string", "null"]},
                            "outcomes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "price": {"type": ["number", "null"]},
                                    },
                                },
                            },
                            "yes_price": {"type": ["number", "null"]},
                            "no_price": {"type": ["number", "null"]},
                            "volume": {"type": ["number", "null"]},
                            "liquidity": {"type": ["number", "null"]},
                            "resolution_date": {"type": ["string", "null"]},
                            "url": {"type": ["string", "null"]},
                            "active": {"type": "boolean"},
                            "last_update": {"type": "string"},
                        },
                    },
                },
                "category": {"type": "string"},
                "source": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_prediction_market_detail",
        "description": (
            "Look up a single prediction market by id or ticker and return its "
            "full detail: question, outcome prices (0-1 probabilities), volume, "
            "liquidity, resolution date, and source URL. Accepts a Polymarket "
            "market id or slug (e.g. 'will-bitcoin-hit-100k') or a Kalshi market "
            "ticker (e.g. 'KXNBAMVP-26'). Use to drill into one market after a "
            "pry_prediction_markets listing, or to check the current crowd "
            "probability for a specific event, e.g. 'what is the market pricing "
            "for the Fed rate decision?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "market_id": {
                    "type": "string",
                    "description": ("Polymarket market id/slug or Kalshi market ticker"),
                },
                "source": {
                    "type": "string",
                    "default": "polymarket",
                    "description": ("Data source: polymarket (default) or kalshi"),
                },
            },
            "required": ["market_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "market_id": {"type": "string"},
                        "source": {"type": "string"},
                        "question": {"type": "string"},
                        "category": {"type": ["string", "null"]},
                        "outcomes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "price": {"type": ["number", "null"]},
                                },
                            },
                        },
                        "yes_price": {"type": ["number", "null"]},
                        "no_price": {"type": ["number", "null"]},
                        "volume": {"type": ["number", "null"]},
                        "liquidity": {"type": ["number", "null"]},
                        "resolution_date": {"type": ["string", "null"]},
                        "url": {"type": ["string", "null"]},
                        "active": {"type": "boolean"},
                        "last_update": {"type": "string"},
                    },
                },
                "market_id": {"type": "string"},
                "source": {"type": "string"},
            },
            "required": ["success"],
        },
    },
]

# Candidate public function names for the datasets.prediction_markets
# modules. Each tool maps to one or more (module, candidate-callables)
# options tried in order, so the dispatcher resolves whichever
# module/function the landed code actually exposes.
_PREDICTION_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_prediction_markets": (
        ("prediction_markets", ("get_prediction_markets",)),
        ("polymarket", ("get_polymarket_markets",)),
        ("kalshi", ("get_kalshi_markets",)),
    ),
    "pry_prediction_market_detail": (
        ("prediction_markets", ("get_prediction_market",)),
        ("polymarket", ("get_polymarket_market",)),
        ("kalshi", ("get_kalshi_market",)),
    ),
}
