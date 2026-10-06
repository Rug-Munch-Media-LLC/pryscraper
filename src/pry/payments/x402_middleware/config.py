"""x402 payment configuration — endpoint/pricing tables (audit E41).

Split out of the former monolithic x402_middleware.py. Import surface
is preserved via the package __init__.
"""

import logging
from typing import Any

from pry.payments.x402 import X402_PRICING

logger = logging.getLogger(__name__)

__all__ = ["X402_GATE_MISCONFIGURED", "X402_PRICING"]

X402_GATE_MISCONFIGURED: Any | None
try:
    from prometheus_client import Counter as _PcCounter

    X402_GATE_MISCONFIGURED = _PcCounter(
        "pry_x402_gate_misconfigured_total",
        "Requests refused because a paid endpoint lacked its pricing entry",
    )
except ImportError as exc:  # optional dependency
    logger.warning(
        "payments_exception_swallowed",
        extra={"error": str(exc), "handler": "<module>"},
    )
    X402_GATE_MISCONFIGURED = None

PAID_ENDPOINTS = {
    "/v1/scrape/methods": "scrape_methods",
    "/v1/scrape": "scrape",
    # Specific prefixes MUST precede their broad parents (first match wins).
    # /v1/crawl/adaptive was previously shadowed by /v1/crawl below.
    "/v1/crawl/adaptive": "crawl",
    "/v1/crawl": "crawl",
    "/v1/extract/css": "extract",
    "/v1/extract/llm": "llm_call",
    "/v1/templates/execute": "template_execute",
    "/v1/templates/batch": "template_batch_execute",
    "/v1/automate": "browser_automation",
    "/v1/monitor": "monitor",
    "/v1/pdf/extract": "pdf_extract",
    # Previously ungated (free) — now paid:
    "/v1/ultimate-scrape": "scrape",
    "/v1/batch": "bulk_crawl",
    "/v1/map": "crawl",
    "/v1/capture": "browser_automation",
    "/v1/graphql": "graphql_query",
    # Crypto market intelligence — paid per call (tool-equivalent REST paths
    # for pry_token_launches / pry_cex_listings / pry_token_security):
    "/v1/crypto/token-launches": "token_launches",
    "/v1/crypto/cex-listings": "cex_listings",
    "/v1/crypto/token-security": "token_security",
    # Data-domain intelligence — paid per call (tool-equivalent REST paths for
    # the eight data-domain packages: legal, real estate, jobs, travel,
    # attention, local, gov, ip). Trailing-slash prefixes gate every sub-route.
    "/v1/legal/": "legal_dockets",
    "/v1/realestate/": "realestate_search",
    "/v1/jobs/": "jobs_list",
    "/v1/travel/": "flights_grid",
    "/v1/attention/": "serp",
    "/v1/local/": "places_search",
    "/v1/gov/": "procurement",
    "/v1/ip/": "patents",
    # Sports-betting intelligence — paid per scan at a flat $0.01 (OddsJam is
    # $249/mo; this is deliberately the "stupid to choose others" price).
    # Explicit path prefixes cover every /v1/sports/* sub-route (e.g. the
    # "/v1/sports/odds" prefix also gates /v1/sports/odds/{event_id}).
    "/v1/sports/odds": "sports_odds",
    "/v1/sports/stats": "sports_stats",
    "/v1/sports/scores": "sports_scores",
    "/v1/sports/arbitrage": "sports_arbitrage",
    "/v1/sports/plus-ev": "sports_plus_ev",
    "/v1/sports/props": "sports_props",
    "/v1/sports/injuries": "sports_injuries",
    "/v1/sports/live": "sports_live",
    # Money-printer sports intelligence — paid per scan at a flat $0.01,
    # same "stupid to choose others" tier as the existing sports suite:
    "/v1/sports/historical": "sports_historical",
    "/v1/sports/betting-percentages": "sports_betting_percentages",
    "/v1/sports/sharp-consensus": "sports_sharp_consensus",
    "/v1/sports/alerts": "sports_alerts",
    # Expanded sportsbook coverage — the 112-book registry aggregate + coverage
    # stats gate under one prefix at the flat $0.01 sports tier.
    "/v1/sports/books": "sports_books",
    # Climate / research intelligence — paid per call at $0.002:
    "/v1/climate/": "weather",
    "/v1/research/": "academic",
    # Events / freight / energy / food / supply intelligence — paid per call
    # at $0.002-$0.005 (cheap reads; deliberate undercut of Ticketmaster /
    # BeenVerified-class APIs). Prefixes cover every sub-route of each domain.
    "/v1/events/": "events_search",
    "/v1/freight/": "freight_rates",
    "/v1/energy/": "energy_lmp",
    "/v1/food/": "food_grocery",
    "/v1/supply/": "supply_imports",
    # App-store / news / deals intelligence — paid per call at $0.002 (cheap
    # reads; deliberate undercut of app-intelligence and deal-tracking APIs).
    # Compliance gates use explicit prefixes so the legacy URL-check route
    # /v1/compliance/check stays free (backwards compatibility).
    "/v1/appstore/": "app_store_search",
    "/v1/news/": "news_search",
    "/v1/compliance/enforcement": "compliance_search",
    "/v1/compliance/watch/": "company_watch",
    "/v1/deals/": "deals_search",
    # Bidding-data intelligence (government contracts + grants) — paid per
    # call at $0.005. Prefix covers every /v1/bidding/* sub-route.
    "/v1/bidding/": "bidding_contracts",
}

# Price tiers for the crypto-market operations. The canonical pricing table
# lives in x402/scheme.py; these are merged defensively here (setdefault) so
# the /v1/crypto/* gates above are never silently skipped (the middleware
# skips gating when the operation is missing from X402_PRICING). Safe to keep
# even after the tiers are promoted to scheme.py — setdefault never clobbers.
_CRYPTO_PRICE_TIERS: dict[str, dict[str, Any]] = {
    "token_launches": {
        "price_usd": 0.002,
        "description": "Crypto token launches / pairs / trending",
    },
    "cex_listings": {
        "price_usd": 0.002,
        "description": "CEX listing & delisting signals",
    },
    "token_security": {
        "price_usd": 0.005,
        "description": "Token security scan",
    },
}
for _operation, _tier in _CRYPTO_PRICE_TIERS.items():
    X402_PRICING.setdefault(_operation, _tier)

# Price tiers for the data-domain operations (legal, real estate, jobs,
# travel, attention, local, gov, ip). Same defensive setdefault merge as the
# crypto tiers above — these keep the /v1/{domain}/* gates from being skipped
# until the tiers are promoted into x402/scheme.py.
_DATA_PRICE_TIERS: dict[str, dict[str, Any]] = {
    "legal_dockets": {
        "price_usd": 0.005,
        "description": "U.S. court docket search (CourtListener)",
    },
    "legal_sec": {
        "price_usd": 0.005,
        "description": "SEC EDGAR filing search / insider trades",
    },
    "legal_sanctions": {
        "price_usd": 0.002,
        "description": "OFAC SDN sanctions name screening",
    },
    "realestate_search": {
        "price_usd": 0.005,
        "description": "Real-estate listing search (Zillow/Redfin)",
    },
    "jobs_list": {
        "price_usd": 0.002,
        "description": "ATS job listings (Greenhouse/Lever/Ashby/Workday)",
    },
    "jobs_salary": {
        "price_usd": 0.002,
        "description": "Salary bands (Levels.fyi)",
    },
    "flights_grid": {
        "price_usd": 0.01,
        "description": "Cheapest-flight-per-day grid (Google Flights)",
    },
    "hotel_rates": {
        "price_usd": 0.01,
        "description": "Per-night hotel rates (Google Hotels/Booking.com)",
    },
    "serp": {
        "price_usd": 0.003,
        "description": "Google SERP scrape (organic + AI Overview + PAA)",
    },
    "trends": {
        "price_usd": 0.003,
        "description": "Google Trends interest timeline",
    },
    "places_search": {
        "price_usd": 0.003,
        "description": "Google Maps local business search",
    },
    "reviews": {
        "price_usd": 0.003,
        "description": "Google Maps / Yelp review history",
    },
    "procurement": {
        "price_usd": 0.005,
        "description": "U.S. federal procurement opportunities (SAM.gov)",
    },
    "recalls": {
        "price_usd": 0.005,
        "description": "CPSC product recalls",
    },
    "patents": {
        "price_usd": 0.005,
        "description": "USPTO patent search",
    },
    "trademarks": {
        "price_usd": 0.005,
        "description": "USPTO trademark search",
    },
}
for _operation, _tier in _DATA_PRICE_TIERS.items():
    X402_PRICING.setdefault(_operation, _tier)

# Price tier for the sports-betting operations. Flat **$0.01 per scan** across
# the whole suite — odds, arbitrage, +EV, props, injuries, live odds, scores,
# stats. Same defensive setdefault merge as the crypto/data tiers above; keeps
# the /v1/sports/* gates from being skipped until promoted into x402/scheme.py.
# The flat price is deliberate: a single scan is a rounding error for any
# bettor, which makes Pry the obvious choice over $249/mo OddsJam.
_SPORTS_PRICE_TIERS: dict[str, dict[str, Any]] = {
    "sports_odds": {
        "price_usd": 0.01,
        "description": "Live sports betting odds (flat $0.01/scan)",
    },
    "sports_stats": {
        "price_usd": 0.01,
        "description": "Player stats (flat $0.01/scan)",
    },
    "sports_scores": {
        "price_usd": 0.01,
        "description": "Sports scores for a day (flat $0.01/scan)",
    },
    "sports_arbitrage": {
        "price_usd": 0.01,
        "description": "Sports arbitrage opportunities (flat $0.01/scan)",
    },
    "sports_plus_ev": {
        "price_usd": 0.01,
        "description": "Positive-EV betting opportunities (flat $0.01/scan)",
    },
    "sports_props": {
        "price_usd": 0.01,
        "description": "Player prop betting lines (flat $0.01/scan)",
    },
    "sports_injuries": {
        "price_usd": 0.01,
        "description": "Sports injury report (flat $0.01/scan)",
    },
    "sports_live": {
        "price_usd": 0.01,
        "description": "Live in-play odds (flat $0.01/scan)",
    },
    # Money-printer sports — flat $0.01/scan like the rest of the suite.
    "sports_historical": {
        "price_usd": 0.01,
        "description": "Historical betting odds (flat $0.01/scan)",
    },
    "sports_betting_percentages": {
        "price_usd": 0.01,
        "description": "Public betting percentages (flat $0.01/scan)",
    },
    "sports_sharp_consensus": {
        "price_usd": 0.01,
        "description": "Sharp consensus lines (flat $0.01/scan)",
    },
    "sports_alerts": {
        "price_usd": 0.01,
        "description": "Money-printer alerts (flat $0.01/scan)",
    },
    # Expanded sportsbook coverage — 112-book registry aggregate + coverage
    # stats at the flat $0.01 sports tier.
    "sports_books": {
        "price_usd": 0.01,
        "description": "112-book aggregated odds / coverage stats (flat $0.01/scan)",
    },
}
for _operation, _tier in _SPORTS_PRICE_TIERS.items():
    X402_PRICING.setdefault(_operation, _tier)

# Price tier for the scrape-method registry. Cheap metadata read at $0.002 —
# same "cheap read" tier as the climate/research lookups. Keeps the
# /v1/scrape/methods gate from being skipped until promoted into x402/scheme.py.
_SCRAPE_METHODS_PRICE_TIER: dict[str, dict[str, Any]] = {
    "scrape_methods": {
        "price_usd": 0.002,
        "description": "Sportsbook scraping-method registry",
    },
}
for _operation, _tier in _SCRAPE_METHODS_PRICE_TIER.items():
    X402_PRICING.setdefault(_operation, _tier)

# Price tiers for the climate / research operations. Cheap reads at $0.002 —
# weather, agriculture indices, academic papers, and domain intelligence are
# low-cost lookups, so gate them well below the sports scans. Same defensive
# setdefault merge as the tiers above; keeps the /v1/climate/* and
# /v1/research/* gates from being skipped until promoted into x402/scheme.py.
_CLIMATE_RESEARCH_PRICE_TIERS: dict[str, dict[str, Any]] = {
    "weather": {
        "price_usd": 0.002,
        "description": "Current weather + short-range forecast",
    },
    "agri": {
        "price_usd": 0.002,
        "description": "Agricultural climate indices / crop conditions",
    },
    "academic": {
        "price_usd": 0.002,
        "description": "Academic paper / preprint search",
    },
    "domain": {
        "price_usd": 0.002,
        "description": "Domain intelligence report (WHOIS/SSL/hosting/tech)",
    },
}
for _operation, _tier in _CLIMATE_RESEARCH_PRICE_TIERS.items():
    X402_PRICING.setdefault(_operation, _tier)

# Price tiers for the events / freight / energy / food / supply operations.
# Cheap reads at $0.002-$0.005 — ticket, container, LMP, grocery, and customs
# lookups are low-cost data pulls, so gate them well below the sports scans.
# Same defensive setdefault merge as the tiers above; keeps the /v1/events/*,
# /v1/freight/*, /v1/energy/*, /v1/food/* and /v1/supply/* gates from being
# skipped until promoted into x402/scheme.py.
_EVENTS_SUPPLY_PRICE_TIERS: dict[str, dict[str, Any]] = {
    "events_search": {
        "price_usd": 0.003,
        "description": "Live event search (Ticketmaster / SeatGeek class feeds)",
    },
    "freight_rates": {
        "price_usd": 0.005,
        "description": "Ocean container / FMC freight rates by route",
    },
    "energy_lmp": {
        "price_usd": 0.002,
        "description": "Electricity locational marginal prices (LMP) by ISO region",
    },
    "food_grocery": {
        "price_usd": 0.002,
        "description": "Grocery prices by item / ZIP and restaurant menu pricing",
    },
    "supply_imports": {
        "price_usd": 0.004,
        "description": "U.S. customs import records by company",
    },
}
for _operation, _tier in _EVENTS_SUPPLY_PRICE_TIERS.items():
    X402_PRICING.setdefault(_operation, _tier)

# Price tiers for the app-store / news / compliance / deals / bidding
# operations. Cheap reads at $0.002-$0.005 — app, news, regulatory, deal,
# and government contract/grant lookups are low-cost data pulls, so gate
# them well below the sports scans. Same defensive setdefault merge as the
# tiers above; keeps the /v1/app-store/*, /v1/news/*, /v1/compliance/*,
# /v1/deals/* and /v1/bidding/* gates from being skipped until promoted
# into x402/scheme.py.
_NEW_DOMAIN_PRICE_TIERS: dict[str, dict[str, Any]] = {
    "app_store_search": {
        "price_usd": 0.002,
        "description": "App Store app search by keyword",
    },
    "app_store_reviews": {
        "price_usd": 0.002,
        "description": "App Store user reviews by app id",
    },
    "news_search": {
        "price_usd": 0.002,
        "description": "News article search by keyword",
    },
    "news_sentiment": {
        "price_usd": 0.002,
        "description": "News sentiment analysis by keyword",
    },
    "compliance_search": {
        "price_usd": 0.003,
        "description": "Regulatory compliance records search by query/agency",
    },
    "company_watch": {
        "price_usd": 0.005,
        "description": "Company regulatory watch — enforcement actions & fines",
    },
    "deals_search": {
        "price_usd": 0.002,
        "description": "Deals / discounts / promotions search",
    },
    "drop_alert": {
        "price_usd": 0.002,
        "description": "Product drop / restock alert check",
    },
    "bidding_contracts": {
        "price_usd": 0.005,
        "description": "Government contract / grant bidding data search",
    },
}
for _operation, _tier in _NEW_DOMAIN_PRICE_TIERS.items():
    X402_PRICING.setdefault(_operation, _tier)
