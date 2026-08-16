"""Pry — site catalog static data.

The single source of truth for "how we scrape each site": one typed entry
per target site that records the scrape method, expected confidence, anti-bot
posture, robots posture, latency budget, and output schema BEFORE any tool is
invoked. Consumers (routers, MCP tools, the executor) look this up up-front
so they can pick a method and set expectations instead of guessing at scrape
time.

Entries are grounded in the actual modules under ``crypto_market/``,
``marketplace/``, ``legal_docs/``, ``real_estate/``, ``jobs/``, ``travel/``,
``attention/``, ``local_data/``, ``gov_data/`` and ``ip_data/`` — the
``method`` value reflects the transport+parse technique each module really
uses (see the per-entry comments). The ``document`` and ``browser`` data
domains are capability entries backed by ``pdf_extractor.py``,
``ocr_extractor.py``, ``stealth_engine.py``, ``camoufox_integration.py``,
``tor_fallback.py`` and ``proxy_manager.py``.

Entry keys (typed, validated by ``site_catalog.registry.SiteCatalog``):

* ``site_id``              — stable unique identifier
* ``domain``               — host (optionally with path prefix) the entry covers
* ``method``               — Pry method vocabulary token, or ``+``-joined
                             compound (e.g. ``"stealth+next_data"``)
* ``confidence``           — 0.0-1.0 expected success probability
* ``anti_bot``             — "none" | "low" | "medium" | "high"
* ``robots``               — "allowed" | "restricted" | "unknown"
* ``latency_ms_estimate``  — median end-to-end latency budget in ms
* ``output_schema``        — normalized output key names
* ``requires_key``         — True when an API key / token is required
* ``data_domain``          — one of the 12 supported data domains
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

# Method vocabulary used across Pry (see METHOD_VOCABULARY in registry.py):
#   api, direct, next_data, embedded_json, stealth, browser, tor, proxy, signed

CATALOG: list[dict[str, Any]] = [
    # ── crypto_market ────────────────────────────────────────────────────────
    # cex_listings.py — public REST tickers, keyless.
    {
        "site_id": "binance",
        "domain": "api.binance.com",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "low",
        "robots": "unknown",
        "latency_ms_estimate": 300,
        "output_schema": ["symbol", "price_usd", "volume_24h", "change_24h_pct"],
        "requires_key": False,
        "data_domain": "crypto",
    },
    {
        "site_id": "bybit",
        "domain": "api.bybit.com",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "low",
        "robots": "unknown",
        "latency_ms_estimate": 300,
        "output_schema": ["symbol", "price_usd", "volume_24h", "change_24h_pct"],
        "requires_key": False,
        "data_domain": "crypto",
    },
    {
        "site_id": "okx",
        "domain": "www.okx.com",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "low",
        "robots": "unknown",
        "latency_ms_estimate": 350,
        "output_schema": ["symbol", "price_usd", "volume_24h", "change_24h_pct"],
        "requires_key": False,
        "data_domain": "crypto",
    },
    {
        "site_id": "coinbase",
        "domain": "api.exchange.coinbase.com",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "unknown",
        "latency_ms_estimate": 300,
        "output_schema": ["product_id", "price_usd", "volume_24h"],
        "requires_key": False,
        "data_domain": "crypto",
    },
    # token_launches.py — DexScreener / CoinGecko / DefiLlama keyless APIs.
    {
        "site_id": "dexscreener",
        "domain": "api.dexscreener.com",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "unknown",
        "latency_ms_estimate": 250,
        "output_schema": [
            "pair_address",
            "base_token",
            "quote_token",
            "price_usd",
            "liquidity_usd",
            "volume_24h",
            "chain",
            "created_at_utc",
        ],
        "requires_key": False,
        "data_domain": "crypto",
    },
    {
        "site_id": "coingecko",
        "domain": "api.coingecko.com",
        "method": "api",
        "confidence": 0.9,
        "anti_bot": "low",
        "robots": "unknown",
        "latency_ms_estimate": 400,
        "output_schema": ["id", "symbol", "name", "price_usd", "market_cap_usd", "volume_24h"],
        "requires_key": False,
        "data_domain": "crypto",
    },
    {
        "site_id": "defillama",
        "domain": "api.llama.fi",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "unknown",
        "latency_ms_estimate": 300,
        "output_schema": ["protocol", "chain", "tvl_usd", "change_24h_pct"],
        "requires_key": False,
        "data_domain": "crypto",
    },
    # token_security.py — GoPlus token-security API.
    {
        "site_id": "goplus",
        "domain": "api.gopluslabs.io",
        "method": "api",
        "confidence": 0.9,
        "anti_bot": "low",
        "robots": "unknown",
        "latency_ms_estimate": 600,
        "output_schema": [
            "contract_address",
            "chain_id",
            "is_honeypot",
            "owner_permissions",
            "liquidity",
            "token_security",
        ],
        "requires_key": False,
        "data_domain": "crypto",
    },
    # ── marketplace ─────────────────────────────────────────────────────────
    # amazon.py — UA-fetch of the public dp/ page; Amazon is a Next.js site so
    # the embedded __NEXT_DATA__ blob carries the product payload. Heavily
    # bot-gated → stealth + next_data, high anti-bot.
    {
        "site_id": "amazon",
        "domain": "www.amazon.com",
        "method": "stealth+next_data",
        "confidence": 0.7,
        "anti_bot": "high",
        "robots": "restricted",
        "latency_ms_estimate": 3500,
        "output_schema": [
            "asin",
            "title",
            "price",
            "rating",
            "review_count",
            "availability",
            "url",
        ],
        "requires_key": False,
        "data_domain": "marketplace",
    },
    # walmart.py — _find_script_json(html, "__NEXT_DATA__") on /ip/ pages.
    {
        "site_id": "walmart",
        "domain": "www.walmart.com",
        "method": "next_data",
        "confidence": 0.7,
        "anti_bot": "medium",
        "robots": "restricted",
        "latency_ms_estimate": 2800,
        "output_schema": ["product_id", "title", "price", "stock", "seller", "url"],
        "requires_key": False,
        "data_domain": "marketplace",
    },
    # tiktok_shop.py — unauthenticated /shop/pdp/render/{id} JSON; bestseller
    # surfaces need signed requests (hence embedded_json + signed).
    {
        "site_id": "tiktok_shop",
        "domain": "www.tiktok.com",
        "method": "embedded_json+signed",
        "confidence": 0.65,
        "anti_bot": "high",
        "robots": "restricted",
        "latency_ms_estimate": 2500,
        "output_schema": ["product_id", "title", "price", "rating", "sold_count", "gmv_estimate"],
        "requires_key": False,
        "data_domain": "marketplace",
    },
    # ── legal_docs ──────────────────────────────────────────────────────────
    # dockets.py — CourtListener REST API v4 (free token optional).
    {
        "site_id": "courtlistener",
        "domain": "www.courtlistener.com",
        "method": "api",
        "confidence": 0.9,
        "anti_bot": "medium",
        "robots": "allowed",
        "latency_ms_estimate": 1200,
        "output_schema": ["docket_id", "case_name", "court", "date_filed", "parties", "url"],
        "requires_key": False,
        "data_domain": "legal",
    },
    # sanctions.py — OFAC SDN downloads as raw JSON/XML/CSV.
    {
        "site_id": "ofac_sdn",
        "domain": "www.treasury.gov",
        "method": "direct",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 1000,
        "output_schema": ["name", "aliases", "addresses", "programs", "sanctions_type"],
        "requires_key": False,
        "data_domain": "legal",
    },
    # sec_filings.py — data.sec.gov company-submissions JSON (descriptive UA).
    {
        "site_id": "sec_edgar",
        "domain": "data.sec.gov",
        "method": "api",
        "confidence": 0.9,
        "anti_bot": "low",
        "robots": "restricted",
        "latency_ms_estimate": 1000,
        "output_schema": ["cik", "company_name", "filings", "document_url"],
        "requires_key": False,
        "data_domain": "legal",
    },
    # sec_filings.py — efts.sec.gov full-text search index JSON.
    {
        "site_id": "sec_ftsearch",
        "domain": "efts.sec.gov",
        "method": "api",
        "confidence": 0.9,
        "anti_bot": "low",
        "robots": "restricted",
        "latency_ms_estimate": 1200,
        "output_schema": ["cik", "company_name", "document_type", "document_url"],
        "requires_key": False,
        "data_domain": "legal",
    },
    # ── real_estate ─────────────────────────────────────────────────────────
    # listings.py — Zillow homedetails/SRP __NEXT_DATA__ JSON; Redfin GIS API.
    {
        "site_id": "zillow",
        "domain": "www.zillow.com",
        "method": "next_data",
        "confidence": 0.6,
        "anti_bot": "high",
        "robots": "restricted",
        "latency_ms_estimate": 3000,
        "output_schema": ["zillow_id", "address", "price", "beds", "baths", "sqft", "listing_url"],
        "requires_key": False,
        "data_domain": "real-estate",
    },
    {
        "site_id": "redfin",
        "domain": "www.redfin.com",
        "method": "api",
        "confidence": 0.7,
        "anti_bot": "medium",
        "robots": "restricted",
        "latency_ms_estimate": 2500,
        "output_schema": ["property_id", "address", "price", "beds", "baths", "sqft"],
        "requires_key": False,
        "data_domain": "real-estate",
    },
    # property_records.py — county ArcGIS FeatureServer REST (e.g. Wake Co.).
    {
        "site_id": "arcgis_parcels",
        "domain": "maps.wakegov.com",
        "method": "api",
        "confidence": 0.9,
        "anti_bot": "low",
        "robots": "unknown",
        "latency_ms_estimate": 1500,
        "output_schema": ["parcel_id", "owner", "address", "assessed_value", "land_use"],
        "requires_key": False,
        "data_domain": "real-estate",
    },
    # ── jobs ────────────────────────────────────────────────────────────────
    # ats.py — Greenhouse / Lever / Ashby public job-board JSON APIs.
    {
        "site_id": "greenhouse",
        "domain": "boards-api.greenhouse.io",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 400,
        "output_schema": ["company", "job_id", "title", "location", "url"],
        "requires_key": False,
        "data_domain": "jobs",
    },
    {
        "site_id": "lever",
        "domain": "api.lever.co",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 400,
        "output_schema": ["company", "posting_id", "title", "location", "url"],
        "requires_key": False,
        "data_domain": "jobs",
    },
    {
        "site_id": "ashby",
        "domain": "api.ashbyhq.com",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 400,
        "output_schema": ["company", "job_id", "title", "location", "url"],
        "requires_key": False,
        "data_domain": "jobs",
    },
    # salary.py — levels.fyi company salary pages fetched with UA headers.
    {
        "site_id": "levels_fyi",
        "domain": "www.levels.fyi",
        "method": "stealth",
        "confidence": 0.6,
        "anti_bot": "medium",
        "robots": "restricted",
        "latency_ms_estimate": 2500,
        "output_schema": ["company", "role", "salary_estimate", "url"],
        "requires_key": False,
        "data_domain": "jobs",
    },
    # ── travel ──────────────────────────────────────────────────────────────
    # flights.py — Google Flights AF_initDataCallback embedded JSON.
    {
        "site_id": "google_flights",
        "domain": "www.google.com/travel/flights",
        "method": "embedded_json",
        "confidence": 0.6,
        "anti_bot": "high",
        "robots": "restricted",
        "latency_ms_estimate": 3200,
        "output_schema": ["origin", "destination", "date", "price", "airline", "duration", "url"],
        "requires_key": False,
        "data_domain": "travel",
    },
    # hotels.py — Google Hotels embedded JSON (primary), Booking.com fallback.
    {
        "site_id": "google_hotels",
        "domain": "www.google.com/travel/hotels",
        "method": "embedded_json",
        "confidence": 0.55,
        "anti_bot": "high",
        "robots": "restricted",
        "latency_ms_estimate": 3200,
        "output_schema": ["hotel_name", "price", "rating", "address", "url"],
        "requires_key": False,
        "data_domain": "travel",
    },
    {
        "site_id": "booking",
        "domain": "www.booking.com",
        "method": "stealth",
        "confidence": 0.6,
        "anti_bot": "high",
        "robots": "restricted",
        "latency_ms_estimate": 3000,
        "output_schema": ["hotel_name", "price", "rating", "location"],
        "requires_key": False,
        "data_domain": "travel",
    },
    # ── attention ───────────────────────────────────────────────────────────
    # ad_intel.py — Facebook Ad Library HTML carries JSON blobs; page is
    # login-gated for some surfaces → may need a browser pass.
    {
        "site_id": "facebook_ads_library",
        "domain": "www.facebook.com/ads/library",
        "method": "embedded_json",
        "confidence": 0.5,
        "anti_bot": "high",
        "robots": "restricted",
        "latency_ms_estimate": 4000,
        "output_schema": ["page_name", "ad_id", "text", "country", "platforms"],
        "requires_key": False,
        "data_domain": "attention",
    },
    # serp.py — google.com/search HTML with browser-ish headers.
    {
        "site_id": "google_serp",
        "domain": "www.google.com/search",
        "method": "stealth",
        "confidence": 0.5,
        "anti_bot": "high",
        "robots": "restricted",
        "latency_ms_estimate": 2500,
        "output_schema": ["title", "url", "snippet", "position"],
        "requires_key": False,
        "data_domain": "attention",
    },
    # trends.py — trends.google.com/trends/api JSON (unofficial, keyless).
    {
        "site_id": "google_trends",
        "domain": "trends.google.com",
        "method": "api",
        "confidence": 0.8,
        "anti_bot": "low",
        "robots": "restricted",
        "latency_ms_estimate": 1500,
        "output_schema": ["keyword", "interest_over_time", "region", "related_queries"],
        "requires_key": False,
        "data_domain": "attention",
    },
    # ── local_data ──────────────────────────────────────────────────────────
    # places.py — Google Maps application/ld+json + embedded JSON blobs.
    {
        "site_id": "google_maps",
        "domain": "www.google.com/maps",
        "method": "embedded_json",
        "confidence": 0.55,
        "anti_bot": "high",
        "robots": "restricted",
        "latency_ms_estimate": 3500,
        "output_schema": [
            "place_id",
            "name",
            "address",
            "rating",
            "review_count",
            "phone",
            "website",
        ],
        "requires_key": False,
        "data_domain": "local",
    },
    # reviews.py — yelp.com/biz/{slug} page with UA headers.
    {
        "site_id": "yelp",
        "domain": "www.yelp.com",
        "method": "stealth",
        "confidence": 0.6,
        "anti_bot": "medium",
        "robots": "restricted",
        "latency_ms_estimate": 3000,
        "output_schema": ["business_name", "rating", "review_count", "address", "url"],
        "requires_key": False,
        "data_domain": "local",
    },
    # ── gov_data ────────────────────────────────────────────────────────────
    # procurement.py — api.sam.gov opportunities/v2/search, REQUIRES a free key.
    {
        "site_id": "sam_gov",
        "domain": "api.sam.gov",
        "method": "api",
        "confidence": 0.9,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 900,
        "output_schema": ["notice_id", "title", "agency", "posted_date", "response_date", "url"],
        "requires_key": True,
        "data_domain": "gov",
    },
    # recalls.py — api.cpsc.gov product-safety recall API.
    {
        "site_id": "cpsc_recalls",
        "domain": "api.cpsc.gov",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 800,
        "output_schema": ["recall_id", "product", "brand", "hazard", "date"],
        "requires_key": False,
        "data_domain": "gov",
    },
    # recalls.py — openFDA /enforcement.json APIs.
    {
        "site_id": "fda_enforcement",
        "domain": "api.fda.gov",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 800,
        "output_schema": ["recall_id", "product", "reason", "classification", "date"],
        "requires_key": False,
        "data_domain": "gov",
    },
    # ── ip_data ─────────────────────────────────────────────────────────────
    # patents.py — patents.google.com/xhr/query JSON (keyless).
    {
        "site_id": "google_patents",
        "domain": "patents.google.com",
        "method": "api",
        "confidence": 0.85,
        "anti_bot": "low",
        "robots": "restricted",
        "latency_ms_estimate": 1200,
        "output_schema": ["patent_id", "title", "assignee", "date", "url"],
        "requires_key": False,
        "data_domain": "ip",
    },
    # trademarks.py — USPTO tmsearch POST JSON API.
    {
        "site_id": "uspto_tmsearch",
        "domain": "tmsearch.uspto.gov",
        "method": "api",
        "confidence": 0.8,
        "anti_bot": "medium",
        "robots": "restricted",
        "latency_ms_estimate": 1500,
        "output_schema": ["serial_no", "mark", "owner", "status", "url"],
        "requires_key": False,
        "data_domain": "ip",
    },
    # trademarks.py — TSDR case-status JSON endpoint.
    {
        "site_id": "uspto_tsdr",
        "domain": "tsdrapi.uspto.gov",
        "method": "api",
        "confidence": 0.85,
        "anti_bot": "medium",
        "robots": "restricted",
        "latency_ms_estimate": 1000,
        "output_schema": ["serial_no", "status", "event_history"],
        "requires_key": False,
        "data_domain": "ip",
    },
    # company_registry.py — Nevada SOS CorpSearch JSON API.
    {
        "site_id": "nv_sos_registry",
        "domain": "nv-sos.elb.us-eas-2.aws.sos.nv.gov",
        "method": "api",
        "confidence": 0.85,
        "anti_bot": "low",
        "robots": "unknown",
        "latency_ms_estimate": 1200,
        "output_schema": ["entity_name", "entity_id", "status", "filing_date"],
        "requires_key": False,
        "data_domain": "ip",
    },
    # ── document (pdf_extractor.py / ocr_extractor.py) ──────────────────────
    # Generic PDF extraction capability (pdfplumber/camelot/pdfminer).
    {
        "site_id": "pdf_extract",
        "domain": "pdf://generic",
        "method": "direct",
        "confidence": 0.9,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 1500,
        "output_schema": ["text", "pages", "tables", "metadata"],
        "requires_key": False,
        "data_domain": "document",
    },
    # Generic image OCR capability (tesseract).
    {
        "site_id": "ocr_extract",
        "domain": "image://generic",
        "method": "direct",
        "confidence": 0.85,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 1200,
        "output_schema": ["text", "confidence", "language"],
        "requires_key": False,
        "data_domain": "document",
    },
    # arXiv — keyless OAI/export API for paper metadata + PDFs.
    {
        "site_id": "arxiv",
        "domain": "export.arxiv.org",
        "method": "api",
        "confidence": 0.95,
        "anti_bot": "none",
        "robots": "allowed",
        "latency_ms_estimate": 800,
        "output_schema": ["title", "authors", "abstract", "pdf_url", "published"],
        "requires_key": False,
        "data_domain": "document",
    },
    # ── browser (stealth_engine.py / camoufox_integration.py / tor / proxy) ─
    # Generic JS-rendered page fallback via Playwright.
    {
        "site_id": "browser_generic",
        "domain": "browser://generic",
        "method": "browser",
        "confidence": 0.6,
        "anti_bot": "medium",
        "robots": "unknown",
        "latency_ms_estimate": 4000,
        "output_schema": ["rendered_html", "screenshot", "dom"],
        "requires_key": False,
        "data_domain": "browser",
    },
    # Anti-fingerprinting stealth browser pass.
    {
        "site_id": "camoufox_stealth",
        "domain": "camoufox://stealth",
        "method": "browser+stealth",
        "confidence": 0.65,
        "anti_bot": "high",
        "robots": "unknown",
        "latency_ms_estimate": 5000,
        "output_schema": ["rendered_html", "screenshot", "fingerprints"],
        "requires_key": False,
        "data_domain": "browser",
    },
    # FlareSolverr challenge solver for Cloudflare-protected pages.
    {
        "site_id": "flaresolverr",
        "domain": "flaresolverr://challenge",
        "method": "browser",
        "confidence": 0.7,
        "anti_bot": "high",
        "robots": "unknown",
        "latency_ms_estimate": 4500,
        "output_schema": ["html", "cookies", "user_agent"],
        "requires_key": False,
        "data_domain": "browser",
    },
    # Tor fallback for geo/network-blocked targets.
    {
        "site_id": "tor_fallback",
        "domain": "tor://fallback",
        "method": "tor",
        "confidence": 0.5,
        "anti_bot": "medium",
        "robots": "unknown",
        "latency_ms_estimate": 6000,
        "output_schema": ["html", "text"],
        "requires_key": False,
        "data_domain": "browser",
    },
    # Rotating proxy pool for geo-restricted targets.
    {
        "site_id": "proxy_rotate",
        "domain": "proxy://rotate",
        "method": "proxy",
        "confidence": 0.6,
        "anti_bot": "medium",
        "robots": "unknown",
        "latency_ms_estimate": 3500,
        "output_schema": ["html", "headers"],
        "requires_key": False,
        "data_domain": "browser",
    },
]
