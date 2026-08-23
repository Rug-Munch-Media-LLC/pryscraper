"""Pry — x402 (HTTP 402 Payment Required) Middleware.
FastAPI/ASGI middleware that gates endpoints behind x402 payments per the
x402 v1 spec from https://github.com/coinbase/x402.

Implements the spec-compliant flow:
- Read the ``PAYMENT-SIGNATURE`` header (Base64-encoded JSON of the signed
  payment payload: ``{"payment_id": "...", "tx_hash": "..."}``).
- On a missing or invalid payment, return ``402 Payment Required`` with the
  ``PAYMENT-REQUIRED`` header (Base64-encoded ``PaymentRequired`` body).
- On a valid payment, call the downstream app and add a ``PAYMENT-RESPONSE``
  header (Base64-encoded settlement receipt) to the response.

Usage: app.add_middleware(X402Middleware, free_paths=["/health", "/v1/templates"])
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import base64
import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from x402 import PAYMENT_VALIDITY_SECONDS, X402_PRICING, X402Handler, validate_client_amount

logger = logging.getLogger(__name__)

# Fail-closed gate firings (paid prefix without pricing). Prometheus-optional:
# the middleware must work without the metrics client installed.
X402_GATE_MISCONFIGURED: Any | None
try:
    from prometheus_client import Counter as _PcCounter

    X402_GATE_MISCONFIGURED = _PcCounter(
        "pry_x402_gate_misconfigured_total",
        "Requests refused because a paid endpoint lacked its pricing entry",
    )
except ImportError:  # optional dependency
    X402_GATE_MISCONFIGURED = None

# Path prefix -> x402 operation. ``path.startswith(prefix)`` gates the
# endpoint, so a bare prefix (e.g. "/v1/capture") covers every sub-route.
# Every operation here MUST exist in X402_PRICING or the gate is skipped.
PAID_ENDPOINTS = {
    # NOTE: prefix order matters — the first matching prefix wins, so the
    # more specific /v1/scrape/methods (scrape-method registry, $0.002) must
    # be listed before the broad /v1/scrape gate.
    "/v1/scrape/methods": "scrape_methods",
    "/v1/scrape": "scrape",
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
    "/v1/crawl/adaptive": "crawl",
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


# ── Route classification (fail-closed gate) ──────────────────────────────────
# Every HTTP route MUST be explicitly classified as free or paid. The old
# behavior silently served any route missing from PAID_ENDPOINTS for free,
# which meant a new endpoint (or a pricing-table regression) leaked paid
# capability at $0. The startup audit (audit_route_classification) plus the
# runtime fail-closed branch below close that hole.
#
# Classification rules, in order:
#   1. exact match in DEFAULT_FREE_PATHS            -> free
#   2. prefix match in DEFAULT_FREE_PREFIXES        -> free
#   3. under the admin router prefix                -> free (loopback-gated)
#   4. prefix match in PAID_ENDPOINTS with the
#      operation present in X402_PRICING            -> paid
#   5. anything else                                -> unclassified (audit failure)

DEFAULT_FREE_PATHS: frozenset[str] = frozenset(
    {
        # Infra / observability / docs
        "/health",
        "/live",
        "/ready",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
        "/metrics",
        "/version",
        "/dashboard",
        "/v0/stats",
        # MCP sub-app mount + SSE transport
        "/mcp",
        "/mcp/health",
        "/mcp/sse",
        # x402 payment flow itself must be free (chicken-and-egg)
        "/v1/x402/pricing",
        "/v1/x402/payment",
        "/v1/x402/verify",
        "/v1/x402/require-payment",
        "/v1/x402/pay",
        "/v1/x402/batch-payment",
        "/v1/x402/batch-verify",
        "/v1/x402/health",
        # Config / capabilities / AI manifests
        "/v1/config",
        "/v1/config/profile/tor",
        "/v1/capabilities",
        "/v1/ai/mcp-config",
        "/v1/ai/gpt-manifest",
        # Job / session management (control plane, not data plane)
        "/v1/job/{job_id}",
        "/v1/jobs",
        "/v1/stream/{job_id}",
        "/v1/session/create",
        "/v1/session/destroy",
        "/v1/session/restore",
        "/v1/session/save",
        "/v1/sessions",
        # Auth connector
        "/v1/auth/captcha",
        "/v1/auth/credentials",
        "/v1/auth/credentials/{credential_id}",
        "/v1/auth/session/health",
        "/v1/auth/sso",
        # Circuit breaker / diagnostics
        "/v1/breaker/reset",
        "/v1/breaker/status",
        "/v1/diagnostics",
        # Proxy management (control plane)
        "/v1/proxy/clicks",
        "/v1/proxy/configure",
        "/v1/proxy/pool",
        "/v1/proxy/providers",
        "/v1/proxy/recommend",
        "/v1/proxy/referrals",
        "/v1/proxy/referrals/{tag}",
        "/v1/proxy/signup",
        "/v1/proxy/status",
        "/v1/proxy/test",
        # Cookie warming / stealth control plane
        "/v1/cookies/sessions",
        "/v1/cookies/warm",
        "/v1/behavior/simulate",
        "/v1/detect-block",
        # Compliance (legacy free check route — see PAID_ENDPOINTS note)
        "/v1/compliance/check",
        # GDPR / privacy (legal obligation routes stay free)
        "/v1/gdpr/audit",
        "/v1/gdpr/consent",
        "/v1/gdpr/consent/revoke",
        "/v1/gdpr/consent/{user_id}",
        "/v1/gdpr/deletion/execute",
        "/v1/gdpr/deletion/request",
        "/v1/gdpr/retention",
        "/v1/gdpr/retention/apply",
        # Webhooks management
        "/v1/webhooks/dead-letter",
        "/v1/webhooks/test",
        # Alerts / destinations / CRM / commerce sync (outbound integrations)
        "/v1/alert/channels",
        "/v1/alert/send",
        "/v1/destination/send",
        "/v1/destinations",
        "/v1/crm/platforms",
        "/v1/crm/sync",
        "/v1/commerce/platforms",
        "/v1/commerce/search",
        "/v1/commerce/sync",
        "/v1/commerce/{marketplace}/{product_id}",
        # Referral program
        "/v1/referrals/catalog",
        "/v1/referrals/click",
        "/v1/referrals/convert",
        "/v1/referrals/stats",
        # Costing / freshness / quality dashboards
        "/v1/costing/costs",
        "/v1/costing/dashboard",
        "/v1/costing/record",
        "/v1/costing/usage",
        "/v1/freshness/check",
        "/v1/freshness/dashboard",
        "/v1/freshness/frequency",
        "/v1/quality/check",
        "/v1/quality/stats",
        # Pipelines (orchestration control plane)
        "/v1/pipe",
        "/v1/pipeline/hook",
        "/v1/pipeline/hooks",
        "/v1/pipeline/run",
        "/v1/pipelines",
        "/v1/pipelines/run",
        "/v1/pipelines/save",
        "/v1/pipelines/steps",
        "/v1/pipelines/validate",
        "/v1/pipelines/{pipeline_id}",
        # Recording / review / reports
        "/v1/record/clear",
        "/v1/record/export",
        "/v1/record/start",
        "/v1/record/step",
        "/v1/review/submit",
        "/v1/review/{review_id}",
        "/v1/review/{review_id}/approve",
        "/v1/review/{review_id}/reject",
        "/v1/reviews",
        "/v1/report/{report_id}",
        "/v1/reports",
        "/v1/reports/generate",
        # Share
        "/v1/share",
        "/share/{share_id}",
        # Templates registry (execution is paid; listing is free)
        "/v1/templates",
        "/v1/templates/{template_id}",
        # Actors / agency marketplace
        "/v1/actors",
        "/v1/actors/create",
        "/v1/actors/{actor_id}/run",
        "/v1/agency/create",
        "/v1/agency/{agency_id}",
        "/v1/agency/{agency_id}/analytics",
        "/v1/agency/{agency_id}/branding",
        "/v1/agency/{agency_id}/clients",
        "/v1/client/{client_id}/quota",
        # Signup automation
        "/v1/signup",
        # NOTE: the following are currently FREE by explicit decision but are
        # candidates for monetization (expensive scrape/data operations).
        # Moving any of them to PAID_ENDPOINTS requires: an operation entry in
        # X402_PRICING, a pricing review, and client migration notice.
        "/v1/extract",
        "/v1/extract-table",
        "/v1/extract-with-review",
        "/v1/parse",
        "/v1/markdown",
        "/v1/schema",
        "/v1/schema/extract",
        "/v1/schema/extract-html",
        "/v1/suggest",
        "/v1/summarize",
        "/v1/categorize",
        "/v1/compare",
        "/v1/diff",
        "/v1/transform",
        "/v1/enrich",
        "/v1/enrich/tech-stack",
        "/v1/dedup/check",
        "/v1/links",
        "/v1/export",
        "/v1/run",
        "/v1/watch",
        "/v1/email/gmail",
        "/v1/email/outlook",
        "/v1/email/scrape",
        "/v1/emails",
        "/v1/screenshot",
        "/v1/ocr/extract",
        "/v1/vision",
        "/v1/vision/models",
        "/v1/camoufox/fetch",
        "/v1/tls/impersonate",
        "/v1/tls/rotate",
        "/v1/shadow-dom",
        "/v1/sse/scrape",
        "/v1/ws/scrape",
        "/v1/seo",
        "/v1/seo/analyze",
        "/v1/seo/keywords",
        "/v1/seo/track",
        "/v1/structure/check",
        "/v1/structure/check-template",
        "/v1/structure/monitor",
        "/v1/intel/analyze",
        "/v1/intel/report",
        "/v1/intel/snapshot",
        "/v1/intel/snapshots/{competitor_id}",
        "/v1/social/{platform}/{handle}",
        "/v1/marketplace/amazon/product/{asin}",
        "/v1/marketplace/amazon/search",
        "/v1/marketplace/tiktok/trending",
        "/v1/marketplace/walmart/product/{product_id}",
        "/v1/health/drug/{drug}",
        "/v1/health/insurance/quotes",
        "/v1/health/trials/search",
        "/v1/health/trials/{nct_id}",
        "/v1/reconcile",
        "/v1/reconcile/schemas",
        "/v1/training/classify-license",
        "/v1/training/clean",
        "/v1/training/compliance/{dataset_id}",
        "/v1/training/export",
    }
)

# Prefix-match free routes (wildcard semantics). Covers everything under the
# MCP messages transport without enumerating session ids.
DEFAULT_FREE_PREFIXES: tuple[str, ...] = ("/mcp/messages/",)


def _admin_prefix() -> str:
    """Resolve the admin router prefix without a hard import cycle.

    routers.admin derives it from PRY_ADMIN_PATH (or a per-process random
    hex), so the value is only stable within one process — which is exactly
    the lifetime this classification matters for.
    """
    try:
        from routers.admin import ADMIN_PREFIX

        return ADMIN_PREFIX
    except Exception:  # noqa: BLE001  # pragma: no cover - admin router optional
        secret = os.getenv("PRY_ADMIN_PATH", "")
        return f"/{secret}" if secret else "/__admin_unavailable__"


def resolve_operation(path: str) -> str | None:
    """Return the x402 operation for a path, or None if no paid prefix matches.

    First matching prefix wins; PAID_ENDPOINTS is ordered so more specific
    prefixes (e.g. /v1/scrape/methods) precede broad ones (/v1/scrape).
    """
    return next((op for ep, op in PAID_ENDPOINTS.items() if path.startswith(ep)), None)


def classify_path(path: str) -> str:
    """Classify a request path as ``free``, ``paid`` or ``misconfigured``.

    Returns ``"misconfigured"`` when a path matches a paid prefix whose
    operation is absent from X402_PRICING — a deployment bug that used to be
    served free.
    """
    if path in DEFAULT_FREE_PATHS:
        return "free"
    if any(path.startswith(p) for p in DEFAULT_FREE_PREFIXES):
        return "free"
    if path.startswith(_admin_prefix()):
        return "free"
    op = resolve_operation(path)
    if op is not None:
        return "paid" if op in X402_PRICING else "misconfigured"
    return "misconfigured"


def iter_app_route_paths(app: Any) -> Iterator[str]:
    """Yield concrete route paths from a FastAPI app (or router route list).

    Recent FastAPI versions wrap included routers in lazy ``_IncludedRouter``
    objects that expose no ``.path`` until first request; recurse into their
    original router to enumerate real routes at startup time.
    """
    routes = app.routes if hasattr(app, "routes") else app
    for route in routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            yield route.path
        elif type(route).__name__ == "_IncludedRouter":
            yield from iter_app_route_paths(route.original_router.routes)
        elif hasattr(route, "path"):  # Mount and other path-carrying nodes
            yield route.path


def audit_route_classification(app: Any) -> list[str]:
    """Return every app route path that is not explicitly free or paid.

    Empty list = gate is fully classified. Called from the api lifespan;
    strict mode raises on non-empty results so an unclassified route can
    never reach production silently.
    """
    return sorted({p for p in iter_app_route_paths(app) if classify_path(p) == "misconfigured"})


def _caller_key_from_scope(scope: dict[str, Any]) -> str:
    """Derive a caller binding key from the ASGI connection.

    Uses the socket peer IP only — X-Forwarded-For is spoofable and must not
    be trusted for payment binding. Returns "" when no client info is present
    (e.g. tests / local unix sockets); such payments still expire.
    """
    client = scope.get("client")
    if client and isinstance(client, (list, tuple)) and len(client) >= 1 and client[0]:
        return str(client[0])
    return ""


class X402Middleware:
    """ASGI middleware that gates paid endpoints behind x402 payments.

    Headers (x402 v1 spec):
    - Request: ``PAYMENT-SIGNATURE: <Base64(JSON of {payment_id, tx_hash, ...})>``
    - 402 response: ``PAYMENT-REQUIRED: <Base64(JSON PaymentRequired)>``
    - 2xx response: ``PAYMENT-RESPONSE: <Base64(JSON settlement receipt)>``
    """

    def __init__(
        self,
        app: Any,
        free_paths: list[str] | None = None,
        free_prefixes: list[str] | None = None,
        wallet: str = "pry-default",
        network: str = "base",
        facilitator_url: str = "https://x402.org/facilitator",
    ) -> None:
        self.app = app
        self.free_paths: frozenset[str] = frozenset(
            free_paths if free_paths is not None else DEFAULT_FREE_PATHS
        )
        self.free_prefixes: tuple[str, ...] = tuple(
            free_prefixes if free_prefixes is not None else DEFAULT_FREE_PREFIXES
        )
        self.wallet = wallet
        self.network = network
        self.facilitator_url = facilitator_url
        self.handler = X402Handler(wallet=wallet, facilitator_url=facilitator_url)
        self.payments: dict[str, dict[str, Any]] = {}

    def _is_free(self, path: str) -> bool:
        """Exact/prefix/admin free-path check (wildcard-aware)."""
        if path in self.free_paths:
            return True
        if any(path.startswith(p) for p in self.free_prefixes):
            return True
        return path.startswith(_admin_prefix())

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # CORS preflight: OPTIONS requests carry no credentials or body and must
        # reach CORSMiddleware so browsers get the Access-Control-Allow-* headers.
        # Never gate preflight behind payment.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if self._is_free(path):
            await self.app(scope, receive, send)
            return

        # Resolve the operation once, up front, so server-side pricing can be
        # enforced against any client-supplied amount.
        operation = resolve_operation(path)
        if not operation:
            # No paid prefix matched. The startup audit guarantees every route
            # is classified; reaching here means the request path escaped both
            # the free lists and PAID_ENDPOINTS (e.g. a dynamic path not backed
            # by a registered route). Serve it — 404s from the router are the
            # correct response for unknown paths, not a payment challenge.
            await self.app(scope, receive, send)
            return
        if operation not in X402_PRICING:
            # FAIL CLOSED: a paid prefix without pricing is a deployment bug.
            # The previous behavior silently served the endpoint for free.
            logger.critical(
                "x402_gate_misconfigured",
                extra={"operation": operation, "path": path},
            )
            if X402_GATE_MISCONFIGURED is not None:
                X402_GATE_MISCONFIGURED.inc()
            body = json.dumps(
                {
                    "error": "payment_gate_misconfigured",
                    "detail": "endpoint is gated but its price is not configured",
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        caller_key = _caller_key_from_scope(scope)

        headers = dict(scope.get("headers", []))
        payment_sig = headers.get(b"payment-signature", b"").decode()
        payment_id_header = headers.get(b"x-payment-id", b"").decode()
        batch_id_header = headers.get(b"x-batch-payment-id", b"").decode()

        # Check pre-verified individual payment (expiry + caller-bound).
        # Refresh first so payments issued by other handlers (e.g. the
        # /v1/x402/pay route) are visible to this middleware instance.
        if payment_id_header:
            self.handler.refresh()
            if self.handler.is_paid(payment_id_header, caller_key=caller_key):
                await self.app(scope, receive, send)
                return

        # Check pre-verified batch payment
        if batch_id_header:
            from x402 import is_batch_paid

            if is_batch_paid(batch_id_header):
                await self.app(scope, receive, send)
                return

        if payment_sig:
            try:
                payload = json.loads(base64.b64decode(payment_sig).decode())
                payment_id = payload.get("payment_id", "")
                tx_hash = payload.get("tx_hash", "") or payload.get("payload", "")
                network = payload.get("network", self.network)
                asset = payload.get("asset", "")
                amount_usd = float(payload.get("amount_usd", 0.0))
                if payment_id and tx_hash:
                    # Server-side pricing is authoritative: never trust the
                    # client-supplied amount. Reject underpayment BEFORE any
                    # facilitator call. ``network`` lets the canonical
                    # SUPPORTED_ASSETS table quote non-1:1 assets correctly.
                    ok, price_reason = validate_client_amount(
                        operation, amount_usd, asset, network=network
                    )
                    if not ok:
                        logger.warning(
                            "x402_underpayment_rejected",
                            extra={"operation": operation, "path": path, "reason": price_reason},
                        )
                        await self._send_payment_required(operation, path, send)
                        return
                    verify_result = await self.handler.verify_payment(
                        payment_id,
                        tx_hash,
                        network=network,
                        asset=asset,
                        amount_usd=amount_usd,
                        operation=operation,
                        caller_key=caller_key,
                    )
                    if verify_result.get("verified"):
                        settlement = await self.handler.settle_payment(
                            payment_id,
                            tx_hash,
                            network=network,
                            asset=asset,
                            amount_usd=amount_usd,
                            operation=operation,
                        )
                        response_b64 = base64.b64encode(json.dumps(settlement).encode()).decode()
                        self.payments[payment_id] = {
                            "payment_id": payment_id,
                            "tx_hash": tx_hash,
                            "caller_key": caller_key,
                            "expires_at": (
                                datetime.now(UTC) + timedelta(seconds=PAYMENT_VALIDITY_SECONDS)
                            ).isoformat(),
                            "verified_at": datetime.now(UTC).isoformat(),
                        }

                        response_b64_bytes = response_b64.encode()

                        async def wrapped_send(message: dict[str, Any]) -> None:
                            if message["type"] == "http.response.start":
                                hdrs = list(message.get("headers", []))
                                hdrs.append((b"payment-response", response_b64_bytes))
                                message["headers"] = hdrs
                            await send(message)

                        await self.app(scope, receive, wrapped_send)
                        return
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("x402_payment_decode_failed", extra={"error": str(e)})

        await self._send_payment_required(operation, path, send)

    async def _send_payment_required(self, operation: str, path: str, send: Any) -> None:
        """Send a spec-compliant 402 Payment Required response.

        The challenge is built in multi-asset mode so agents see the full
        canonical acceptance surface (every SUPPORTED_ASSETS network/asset
        keyed by CAIP-2 network id) in the body and the PAYMENT-REQUIRED
        header.
        """
        body, x402_headers = self.handler.create_payment_required(
            operation, resource=path, multi_asset=True
        )
        body_bytes = json.dumps(body).encode()

        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body_bytes)).encode()),
        ]
        for k, v in x402_headers.items():
            response_headers.append((k.lower().encode(), v.encode()))

        await send(
            {
                "type": "http.response.start",
                "status": 402,
                "headers": response_headers,
            }
        )
        await send({"type": "http.response.body", "body": body_bytes})
