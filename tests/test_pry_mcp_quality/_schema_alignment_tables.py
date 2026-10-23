# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Harness tables for the 20 tools whose schemas were realigned on 2026-10-23.

Commits ``a146f9d4`` (14 schemas) and ``6994f5a6`` (6 phantom-field schemas)
corrected ``outputSchema`` declarations that contradicted what the handlers
emit — declared objects that were really arrays, and declared fields
(``data.content``, ``availability``, ``reviews_count``, ``market_id``,
``team``, ``sport``) that no handler ever wrote.

The schemas were fixed; nothing locked them. These tables wire every affected
tool to its emitter so the fix cannot silently regress.
"""

from __future__ import annotations

from typing import Any

from ._schema_payloads_commerce import COMMERCE_PAYLOADS
from ._schema_payloads_signal import SIGNAL_PAYLOADS

#: tool -> the payload its emitter writes (see the two payload modules).
PAYLOADS: dict[str, Any] = {**COMMERCE_PAYLOADS, **SIGNAL_PAYLOADS}

#: tool -> (domain module, handler name(s), call arguments). A handler that
#: imports its sibling fetchers directly needs every name stubbed, not just the
#: entry point, or the stub raises ImportError inside the handler.
ALIGNED_LOCAL: dict[str, tuple[str, str | tuple[str, ...], dict[str, Any]]] = {
    "pry_amazon_product": (
        "pry.commerce.marketplace.amazon",
        "get_product",
        {"asin": "B08N5WRWNW"},
    ),
    "pry_amazon_search": (
        "pry.commerce.marketplace.amazon",
        "search_products",
        {"query": "wireless keyboard", "limit": 5},
    ),
    "pry_walmart_product": (
        "pry.commerce.marketplace.walmart",
        "get_product",
        {"product_id": "4JH7P89H7X5P"},
    ),
    "pry_tiktok_trending": (
        "pry.commerce.marketplace.tiktok_shop",
        "get_trending",
        {"limit": 5},
    ),
    "pry_app_search": (
        "app_store_data.apple",
        "search_apps",
        {"query": "crypto wallet", "country": "us", "limit": 5},
    ),
    "pry_app_reviews": (
        "app_store_data.apple",
        "get_reviews",
        {"app_id": "com.coinbase.app", "limit": 5},
    ),
    "pry_grants": (
        "bidding_data.grants",
        "search_grants",
        {"query": "small business innovation research", "agency": "NSF", "limit": 5},
    ),
    "pry_drop_alert": (
        "deals_data.drops",
        "check_drop_alerts",
        {"product": "RTX 5090", "limit": 5},
    ),
    "pry_flights_grid": (
        "travel.flights",
        "cheapest_date_grid",
        {"origin": "JFK", "dest": "CDG", "start_date": "2026-09-01", "end_date": "2026-09-30"},
    ),
    "pry_resale": ("events_data.tickets", "get_resale_prices", {"event_id": "vv1aZt7B8v"}),
    "pry_token_launches": (
        "crypto_market.token_launches",
        ("get_new_tokens", "get_new_pairs", "get_trending_tokens"),
        {"chain": "solana", "limit": 5},
    ),
    "pry_news": (
        "news_data.headlines",
        "get_headlines",
        {"query": "crypto regulation", "language": "en", "limit": 5},
    ),
    "pry_sentiment": ("news_data.sentiment", "get_sentiment", {"query": "Bitcoin ETF", "limit": 5}),
    "pry_weather": ("climate_data.weather", "get_forecast", {"location": "38.9072,-77.0369"}),
    "pry_prediction_market_detail": (
        "sports_data.prediction_markets_reexport",
        "get_prediction_market",
        {"market_id": "0x1f2e3d"},
    ),
    "pry_lineups": ("sports_data.player_intel", "get_lineups", {"team": "Lakers"}),
    "pry_props_matchup": (
        "sports_data.player_intel",
        "get_props_vs_matchup",
        {"home_team": "Lakers", "away_team": "Celtics"},
    ),
    "pry_sharp_report": ("sports_data.sharp_intel", "get_sharp_report", {"sport": "nba"}),
}

#: tool -> (call arguments, REST payload returned by Pry's HTTP API).
ALIGNED_REST: dict[str, tuple[dict[str, Any], Any]] = {
    "pry_referrals": (
        {"category": "proxies"},
        {
            "success": True,
            "data": [
                {
                    "name": "Bright Data",
                    "category": "proxies",
                    "url": "https://brightdata.com/?utm_source=pry",
                }
            ],
        },
    ),
    "pry_screenshot": (
        {"url": "https://example.com/checkout"},
        {"success": True, "data": {"screenshot": "iVBORw0KGgoAAAANSUhEUg=="}},
    ),
}

#: Emitter module whose string literals must cover each declared field.
#: ``pry_referrals`` is absent on purpose: its items are untyped REST records.
EMITTER_MODULES: dict[str, str] = {name: entry[0] for name, entry in ALIGNED_LOCAL.items()} | {
    "pry_screenshot": "pry.api.routers.core.automation"
}

#: tool -> (module, handler, arguments, identifier echoed in the failure).
EMPTY_PRODUCT_CASES: dict[str, tuple[str, str, dict[str, Any], str]] = {
    "pry_amazon_product": (
        "pry.commerce.marketplace.amazon",
        "get_product",
        {"asin": "B08N5WRWNW"},
        "B08N5WRWNW",
    ),
    "pry_walmart_product": (
        "pry.commerce.marketplace.walmart",
        "get_product",
        {"product_id": "4JH7P89H7X5P"},
        "4JH7P89H7X5P",
    ),
}

#: The alignment set: 14 schemas (a146f9d4) + 6 phantom-field ones (6994f5a6).
ALIGNED_TOOL_NAMES: frozenset[str] = frozenset(ALIGNED_LOCAL) | frozenset(ALIGNED_REST)

assert len(ALIGNED_TOOL_NAMES) == 20, "alignment set must stay at 20 tools"
assert set(PAYLOADS) == set(ALIGNED_LOCAL), "every local tool needs an emitter payload"
