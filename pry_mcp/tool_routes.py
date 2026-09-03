"""MCP-to-API route mapping for the Pry fallback server.

This module defines the single source of truth for how MCP tool names map to
their corresponding REST API (method, path) tuples. The fallback server uses
this mapping to proxy tool calls to the Pry API when a domain module has not
landed yet and the guarded local dispatch was declined.

Each entry maps a tool name to a ``(HTTP method, API path)`` tuple.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

TOOL_ROUTES: dict[str, tuple[str, str]] = {
    "pry_scrape": ("POST", "/v1/scrape"),
    "pry_crawl": ("POST", "/v1/crawl"),
    "pry_extract": ("POST", "/v1/extract/css"),
    "pry_template": ("POST", "/v1/templates/execute"),
    "pry_search_templates": ("GET", "/v1/templates"),
    "pry_monitor": ("POST", "/v1/monitor"),
    "pry_compliance": ("POST", "/v1/compliance/check"),
    "pry_enrich": ("POST", "/v1/enrich"),
    "pry_parse_document": ("POST", "/v1/parse"),
    "pry_screenshot": ("POST", "/v1/screenshot"),
    "pry_x402_pricing": ("GET", "/v1/x402/pricing"),
    "pry_balance": ("POST", "/v1/billing/balance"),
    "pry_buy_pack": ("POST", "/v1/billing/purchase"),
    "pry_referrals": ("GET", "/v1/referrals/catalog"),
    # Data-domain REST fallbacks (used when a domain module has not
    # landed yet and the guarded local dispatch was declined):
    "pry_legal_dockets": ("GET", "/v1/legal/dockets/search"),
    "pry_legal_sec": ("GET", "/v1/legal/sec/search"),
    "pry_legal_sanctions": ("GET", "/v1/legal/sanctions/"),
    "pry_realestate_search": ("GET", "/v1/realestate/search"),
    "pry_jobs_list": ("GET", "/v1/jobs/"),
    "pry_jobs_salary": ("GET", "/v1/jobs/salary/"),
    "pry_flights_grid": ("GET", "/v1/travel/flights/grid"),
    "pry_hotel_rates": ("GET", "/v1/travel/hotels/rates"),
    "pry_serp": ("GET", "/v1/attention/serp"),
    "pry_trends": ("GET", "/v1/attention/trends"),
    "pry_places_search": ("GET", "/v1/local/places/search"),
    "pry_reviews": ("GET", "/v1/local/reviews/"),
    "pry_procurement": ("GET", "/v1/gov/procurement"),
    "pry_recalls": ("GET", "/v1/gov/recalls"),
    "pry_patents": ("GET", "/v1/ip/patents"),
    "pry_trademarks": ("GET", "/v1/ip/trademarks"),
    # Sports-betting REST fallbacks (used when a sports_data module
    # has not landed yet and the guarded local dispatch was declined):
    "pry_odds": ("GET", "/v1/sports/odds"),
    "pry_arbitrage": ("GET", "/v1/sports/arbitrage"),
    "pry_plus_ev": ("GET", "/v1/sports/plus-ev"),
    "pry_props": ("GET", "/v1/sports/props"),
    "pry_injuries": ("GET", "/v1/sports/injuries"),
    "pry_live_odds": ("GET", "/v1/sports/live"),
    "pry_scores": ("GET", "/v1/sports/scores"),
    # Money-printer sports REST fallbacks (historical / percentages /
    # consensus / alerts land from parallel agents):
    "pry_historical_odds": ("GET", "/v1/sports/historical"),
    "pry_betting_percentages": ("GET", "/v1/sports/betting-percentages"),
    "pry_sharp_consensus": ("GET", "/v1/sports/sharp-consensus"),
    "pry_alerts": ("GET", "/v1/sports/alerts"),
    # Expanded sportsbook coverage REST fallbacks (112-book
    # registry + scrape-method registry land from parallel agents):
    "pry_books": ("GET", "/v1/sports/books"),
    "pry_book_coverage": ("GET", "/v1/sports/books/coverage"),
    "pry_scrape_methods": ("GET", "/v1/scrape/methods"),
    # pry_all_sources has no dedicated REST route — degrade to the
    # base odds endpoint (the guarded local dispatch serves the
    # full get_odds_multi path whenever sports_data.odds landed).
    "pry_all_sources": ("GET", "/v1/sports/odds"),
    # Climate / research REST fallbacks (climate_data / research_data
    # land from parallel agents):
    "pry_weather": ("GET", "/v1/climate/weather"),
    "pry_agri": ("GET", "/v1/climate/agri"),
    "pry_papers": ("GET", "/v1/research/papers"),
    "pry_domain": ("GET", "/v1/research/domain"),
    # Events / freight / energy / food / supply REST fallbacks
    # (events_data, freight_data, energy_data, food_data,
    # supply_data land from parallel agents):
    "pry_events": ("GET", "/v1/events/search"),
    "pry_resale": ("GET", "/v1/events/resale"),
    "pry_freight": ("GET", "/v1/freight/rates"),
    "pry_energy_lmp": ("GET", "/v1/energy/lmp"),
    "pry_grocery": ("GET", "/v1/food/grocery"),
    "pry_restaurant": ("GET", "/v1/food/restaurants/menu"),
    "pry_imports": ("GET", "/v1/supply/imports"),
    "pry_firmographics": ("GET", "/v1/supply/firmographics"),
    # App-store / news / compliance / deals REST fallbacks
    # (app_store_data, news_data, compliance_data, deals_data land
    # from parallel agents). pry_compliance keeps its legacy
    # URL-check REST route (POST /v1/compliance/check) — the
    # query/agency regulatory mode is served by the guarded local
    # dispatcher (call_compliance_tool).
    "pry_app_search": ("GET", "/v1/appstore/search"),
    "pry_app_reviews": ("GET", "/v1/appstore/apple/"),
    "pry_news": ("GET", "/v1/news/headlines"),
    "pry_sentiment": ("GET", "/v1/news/sentiment"),
    "pry_company_watch": ("GET", "/v1/compliance/watch/"),
    "pry_deals": ("GET", "/v1/deals/search"),
    "pry_drop_alert": ("GET", "/v1/deals/drops/check"),
}
