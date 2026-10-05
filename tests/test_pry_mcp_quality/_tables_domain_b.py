# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Domain round-trip table (part B): the parallel-built data-domain packages
(events, freight, energy, food, supply), sports books, app-store, news,
compliance, deals, bidding."""

from __future__ import annotations

from typing import Any

DOMAIN_TOOLS_B: dict[str, tuple[str, tuple[str, ...], dict[str, Any]]] = {
    # events_data / freight_data / energy_data / food_data / supply_data
    # (the five new parallel-built data-domain packages):
    "pry_events": (
        "events_data.tickets",
        ("search_events", "find_events", "get_events", "events"),
        {"query": "Taylor Swift", "location": "New York", "limit": 5},
    ),
    "pry_resale": (
        "events_data.tickets",
        ("get_resale_prices", "resale_prices", "get_resale"),
        {"event_id": "vv1aZt7B8v"},
    ),
    "pry_freight": (
        "freight_data.rates",
        ("get_container_rates", "get_fmc_contracts", "container_rates"),
        {"route": "Shanghai to Los Angeles", "limit": 5},
    ),
    "pry_energy_lmp": (
        "energy_data.lmp",
        ("get_lmp", "get_lmp_prices", "lmp_prices", "get_fuel_prices", "fuel_prices"),
        {"region": "ERCOT", "date": "2026-08-16"},
    ),
    "pry_grocery": (
        "food_data.grocery",
        ("get_grocery_prices", "grocery_prices", "get_prices"),
        {"query": "eggs", "zip": "10001", "limit": 5},
    ),
    "pry_restaurant": (
        "food_data.restaurants",
        ("get_restaurant_menu", "restaurant_menu", "get_menu"),
        {"name": "Katz's Delicatessen", "location": "New York"},
    ),
    "pry_imports": (
        "supply_data.imports",
        ("get_import_records", "import_records", "get_imports"),
        {"company": "Tesla Inc", "limit": 5},
    ),
    "pry_firmographics": (
        "supply_data.firmographics",
        ("get_company_firmographics", "company_firmographics", "get_firmographics"),
        {"company": "Rug Munch Media"},
    ),
    "pry_books": (
        "sports_data.books",
        ("get_all_books_odds",),
        {"sport": "basketball_nba", "market": "h2h", "limit": 5},
    ),
    "pry_book_coverage": ("sports_data.books", ("books_coverage",), {}),
    "pry_all_sources": (
        "sports_data.odds",
        ("get_odds_multi",),
        {"event_id": "eid123", "market": "h2h", "limit": 5, "sources": "all"},
    ),
    # app_store_data / news_data / compliance_data / deals_data (the four
    # newest parallel-built data-domain packages):
    "pry_app_search": (
        "app_store_data.apple",
        ("search_apps", "app_search", "search_products", "search"),
        {"query": "crypto wallet", "country": "us", "limit": 5},
    ),
    "pry_app_reviews": (
        "app_store_data.apple",
        ("get_reviews", "app_reviews", "get_app_reviews"),
        {"app_id": "com.coinbase.app", "limit": 5},
    ),
    "pry_news": (
        "news_data.headlines",
        ("get_headlines", "search_news", "news_search", "search_articles", "get_news"),
        {"query": "crypto regulation", "language": "en", "limit": 5},
    ),
    "pry_sentiment": (
        "news_data.sentiment",
        ("get_sentiment", "sentiment_analysis", "analyze_sentiment", "news_sentiment"),
        {"query": "Bitcoin ETF", "limit": 5},
    ),
    # pry_compliance's query/agency mode dispatches to compliance_data; its
    # legacy url-only mode falls through to the REST proxy (covered by
    # test_pry_compliance_url_falls_through_to_rest_proxy).
    "pry_compliance": (
        "compliance_data.enforcement",
        ("search_enforcement", "search_compliance", "compliance_search", "get_compliance"),
        {"query": "Binance", "agency": "SEC", "limit": 5},
    ),
    "pry_company_watch": (
        "compliance_data.enforcement",
        ("watch_company", "company_watch", "get_company_watch"),
        {"company": "OpenAI", "limit": 5},
    ),
    "pry_deals": (
        "deals_data.coupons",
        ("search_deals", "get_deals", "deals_search", "find_deals"),
        {"query": "PS5", "limit": 5},
    ),
    "pry_drop_alert": (
        "deals_data.drops",
        ("check_drop_alerts", "list_alerts", "get_drop_alerts", "drop_alerts"),
        {"product": "RTX 5090", "limit": 5},
    ),
    # bidding_data (government contracts + grants) — the newest parallel-built
    # data-domain package:
    "pry_contracts": (
        "bidding_data.contracts",
        ("search_contracts", "get_contracts", "contracts_search", "find_contracts"),
        {"query": "cybersecurity", "agency": "DHS", "limit": 5},
    ),
    "pry_grants": (
        "bidding_data.grants",
        ("search_grants", "get_grants", "grants_search", "find_grants"),
        {"query": "small business innovation research", "agency": "NSF", "limit": 5},
    ),
}
