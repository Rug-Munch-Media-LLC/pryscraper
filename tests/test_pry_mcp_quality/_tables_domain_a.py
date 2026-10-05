# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Domain round-trip table: crypto, sports, climate, research, commerce,
legal, real estate, jobs, travel, attention, local, gov, ip."""

from __future__ import annotations

from typing import Any

# Domain-dispatched tools: name -> (module to patch, function names to mock,
# sample arguments). The module names match the guarded imports in
# pry_mcp.tools; the data-domain packages are built in parallel, so these run
# the success path with mocked modules (no network).
DOMAIN_TOOLS_A: dict[str, tuple[str, tuple[str, ...], dict[str, Any]]] = {
    "pry_token_launches": (
        "crypto_market.token_launches",
        ("get_new_tokens", "get_new_pairs", "get_trending_tokens"),
        {"chain": "solana", "limit": 5},
    ),
    "pry_cex_listings": (
        "crypto_market.cex_listings",
        ("get_listing_signals",),
        {"exchanges": ["binance"], "lookback_hours": 24},
    ),
    "pry_token_security": (
        "crypto_market.token_security",
        ("scan_token",),
        {"chain": "solana", "address": "So11111111111111111111111111111111111111112"},
    ),
    "pry_kol_leaderboards": (
        "crypto_market.kol_leaderboards",
        ("fetch_kol_leaderboards",),
        {"limit": 25, "source": "kolscan_leaderboard"},
    ),
    "pry_odds": ("sports_data.odds", ("get_odds",), {"sport": "basketball_nba", "limit": 5}),
    "pry_arbitrage": (
        "sports_data.arbitrage",
        ("find_arbitrage",),
        {"sport": "all", "min_yield_pct": 0.5},
    ),
    "pry_plus_ev": (
        "sports_data.ev",
        ("find_plus_ev",),
        {"sharp_book": "pinnacle", "min_ev_pct": 2.0},
    ),
    "pry_props": (
        "sports_data.props",
        ("get_player_props",),
        {"player": "LeBron James", "sport": "basketball_nba", "limit": 5},
    ),
    "pry_injuries": (
        "sports_data.injuries",
        ("get_injuries",),
        {"sport": "basketball_nba", "team": "all"},
    ),
    "pry_live_odds": ("sports_data.live", ("get_live_odds",), {"sport": "all", "limit": 5}),
    "pry_scores": (
        "sports_data.scores",
        ("get_scores",),
        {"sport": "basketball_nba", "date": "today"},
    ),
    "pry_historical_odds": (
        "sports_data.historical",
        ("get_historical_odds",),
        {"sport": "basketball_nba", "event_id": "e1", "date": "2026-08-01", "limit": 5},
    ),
    "pry_betting_percentages": (
        "sports_data.betting_percentages",
        ("get_betting_percentages",),
        {"event_id": "e1", "sport": "basketball_nba", "limit": 5},
    ),
    "pry_sharp_consensus": (
        "sports_data.sharp_intel",
        ("get_consensus_sharp_picks",),
        {},
    ),
    "pry_alerts": (
        "sports_data.alerts",
        ("list_alerts",),
        {"alert_type": "line_move", "sport": "all", "limit": 5},
    ),
    "pry_weather": (
        "climate_data.weather",
        ("get_forecast",),
        {"location": "38.9072,-77.0369", "forecast_days": 2},
    ),
    "pry_agri": (
        "climate_data.agri",
        ("get_crop_prices",),
        {"crop": "corn", "region": "Iowa", "limit": 5},
    ),
    "pry_papers": (
        "research_data.academic",
        ("search_papers",),
        {"query": "retrieval augmented generation", "limit": 5},
    ),
    "pry_domain": (
        "research_data.domain",
        ("whois_lookup",),
        {"domain": "example.com", "include_tech": True},
    ),
    "pry_amazon_product": (
        "pry.commerce.marketplace.amazon",
        ("get_product",),
        {"asin": "B08N5WRWNW"},
    ),
    "pry_amazon_search": (
        "pry.commerce.marketplace.amazon",
        ("search_products",),
        {"query": "wireless keyboard", "limit": 5},
    ),
    "pry_walmart_product": (
        "pry.commerce.marketplace.walmart",
        ("get_product",),
        {"product_id": "4JH7P89H7X5P"},
    ),
    "pry_tiktok_trending": (
        "pry.commerce.marketplace.tiktok_shop",
        ("get_trending",),
        {"limit": 5},
    ),
    "pry_legal_dockets": (
        "legal_docs.dockets",
        ("search_dockets",),
        {"query": "OpenAI copyright", "limit": 2},
    ),
    "pry_legal_sec": (
        "legal_docs.sec_filings",
        ("search_filings",),
        {"ticker": "AAPL", "form_type": "8-K", "limit": 2},
    ),
    "pry_legal_sanctions": (
        "legal_docs.sanctions",
        ("screen_name",),
        {"name": "Vladimir Potanin"},
    ),
    "pry_realestate_search": (
        "real_estate.listings",
        ("search_listings",),
        {"location": "Austin, TX", "status": "for_sale", "limit": 2},
    ),
    "pry_jobs_list": (
        "jobs.ats",
        ("list_jobs",),
        {"company": "stripe", "board": "greenhouse", "limit": 2},
    ),
    "pry_jobs_salary": (
        "jobs.salary",
        ("get_salary",),
        {"company": "google", "role": "software_engineer"},
    ),
    "pry_flights_grid": (
        "travel.flights",
        ("cheapest_date_grid",),
        {"origin": "JFK", "dest": "CDG", "start_date": "2026-09-01", "end_date": "2026-09-30"},
    ),
    "pry_hotel_rates": (
        "travel.hotels",
        ("get_hotel_rates",),
        {"hotel_name": "Ritz Paris", "checkin": "2026-09-10", "checkout": "2026-09-14"},
    ),
    "pry_serp": ("attention.serp", ("serp",), {"q": "best wireless keyboard", "num": 5}),
    "pry_trends": (
        "attention.trends",
        ("trend_interest",),
        {"keyword": "AI agents", "timeframe": "today 3-m"},
    ),
    "pry_places_search": (
        "local_data.places",
        ("search_places",),
        {"query": "taco", "location": "Austin TX", "limit": 2},
    ),
    "pry_reviews": (
        "local_data.reviews",
        ("get_reviews",),
        {"place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4", "source": "google", "limit": 2},
    ),
    # gov_data / ip_data resolve candidate function names via __import__.
    "pry_procurement": (
        "gov_data",
        ("search_opportunities",),
        {"query": "cybersecurity", "limit": 2},
    ),
    "pry_recalls": ("gov_data", ("search_recalls",), {"query": "e-bike battery", "limit": 2}),
    "pry_patents": ("ip_data", ("search_patents",), {"query": "blockchain identity", "limit": 2}),
    "pry_trademarks": (
        "ip_data",
        ("search_trademarks",),
        {"query": "RugMunch", "limit": 2},
    ),
}
