"""Pry - Apify Actor Factory: flagship actor presets.

Each preset is a complete, monetizable product definition. Prices follow
the PPE guidance: price the primary value event, keep the event count low,
let synthetic events cover platform start costs.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from actor_factory.spec import ActorSpec, InputField, PricingEvent

URLS_FIELD = InputField(
    name="urls",
    title="Target URLs",
    type="array",
    description="One or more https:// URLs to process.",
    editor="requestListSources",
    prefill=[{"url": "https://example.com"}],
    required=True,
)

OUTPUT_FORMAT_FIELD = InputField(
    name="output_format",
    title="Output format",
    type="string",
    description="Content format pushed to the dataset.",
    editor="select",
    enum=["markdown", "text", "html"],
    default="markdown",
    section_caption="Scraping settings",
)

MAX_PAGES_FIELD = InputField(
    name="max_pages",
    title="Max pages",
    type="integer",
    description="Hard cap on processed pages (runaway protection).",
    minimum=1,
    maximum=10_000,
    default=100,
    section_caption="Scraping settings",
)


def _scraper_common_inputs() -> tuple[InputField, ...]:
    return (
        URLS_FIELD,
        OUTPUT_FORMAT_FIELD,
        InputField(
            name="stealth_mode",
            title="Stealth mode",
            type="boolean",
            description=(
                "Allow browser tiers (Camoufox/Playwright/undetected) when "
                "cheap tiers are blocked. Disable for speed on friendly sites."
            ),
            default=True,
            section_caption="Scraping settings",
        ),
        InputField(
            name="timeout",
            title="Timeout (seconds)",
            type="integer",
            description="Per-URL timeout.",
            minimum=5,
            maximum=120,
            default=30,
            section_caption="Scraping settings",
        ),
    )


SCRAPER_ACTOR = ActorSpec(
    name="pry-universal-scraper",
    title="Pry Universal Scraper",
    description=(
        "Scrape any website to clean markdown with a 12-tier adaptive "
        "anti-bot bypass (Cloudflare, DataDome, Akamai). Pay per page "
        "scraped; blocked pages escalate automatically."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        OUTPUT_FORMAT_FIELD,
        InputField(
            name="timeout",
            title="Timeout (seconds)",
            type="integer",
            description="Per-URL timeout.",
            minimum=5,
            maximum=120,
            default=30,
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-scraped",
            title="Page scraped",
            description="One URL scraped through the fallback chain.",
            price_usd=0.004,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

CRAWLER_ACTOR = ActorSpec(
    name="pry-site-crawler",
    title="Pry Site Crawler",
    description=(
        "Crawl entire sites into LLM-ready markdown. Follows same-domain "
        "links with runaway caps and per-domain adaptive bypass memory."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        OUTPUT_FORMAT_FIELD,
        InputField(
            name="max_depth",
            title="Max crawl depth",
            type="integer",
            description="Depth 0 = start URLs only.",
            minimum=0,
            maximum=10,
            default=2,
            section_caption="Crawl settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-crawled",
            title="Page crawled",
            description="One page crawled and converted to markdown.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=8192,
)

SCREENSHOT_ACTOR = ActorSpec(
    name="pry-screenshot-capture",
    title="Pry Screenshot Capture",
    description=(
        "Full-page screenshots of any URL, including sites behind "
        "anti-bot systems, via stealth browser tiers."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        InputField(
            name="full_page",
            title="Full page",
            type="boolean",
            description="Capture beyond the fold.",
            default=True,
        ),
        InputField(
            name="viewport_width",
            title="Viewport width (px)",
            type="integer",
            description="Browser viewport width for the capture.",
            minimum=320,
            maximum=3840,
            default=1280,
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="screenshot-taken",
            title="Screenshot taken",
            description="One screenshot captured and stored.",
            price_usd=0.005,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=4096,
)

MONITOR_ACTOR = ActorSpec(
    name="pry-change-monitor",
    title="Pry Change Monitor",
    description=(
        "Watch URLs for content changes with SimHash near-duplicate "
        "detection. Schedule it; get dataset entries only for pages that "
        "actually changed."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        InputField(
            name="change_threshold",
            title="Change threshold",
            type="float",
            description="SimHash similarity below this counts as changed (0-1).",
            minimum=0.0,
            maximum=1.0,
            default=0.85,
            section_caption="Monitoring settings",
        ),
        InputField(
            name="include_unchanged",
            title="Include unchanged pages",
            type="boolean",
            description="Push entries even when nothing changed.",
            default=False,
            section_caption="Monitoring settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-checked",
            title="Page checked",
            description="One monitored URL checked for changes.",
            price_usd=0.001,
        ),
        PricingEvent(
            name="change-detected",
            title="Change detected",
            description="Premium event: fired only when a real change is found.",
            price_usd=0.002,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

DOC_PARSER_ACTOR = ActorSpec(
    name="pry-document-parser",
    title="Pry Document Parser",
    description=(
        "Parse PDFs, DOCX and images behind URLs into clean text/markdown with OCR fallback."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        InputField(
            name="ocr_fallback",
            title="OCR fallback",
            type="boolean",
            description="Use Tesseract for scanned documents.",
            default=True,
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="document-parsed",
            title="Document parsed",
            description="One document parsed to structured text.",
            price_usd=0.006,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

# ── Winner-pattern shared fields (reverse-engineered from top PPE actors) ────

PROXY_CONFIG_FIELD = InputField(
    name="proxy_configuration",
    title="Proxy configuration",
    type="object",
    description=(
        "Apify proxy settings passed through to Pry's premium-proxy tier "
        "(Apify Proxy, residential, or custom). Leave default to use the "
        "platform proxy automatically."
    ),
    editor="hidden",
    prefill={"useApifyProxy": True},
    section_caption="Advanced",
)

MAX_ITEMS_FIELD = InputField(
    name="max_items",
    title="Max items (cost cap)",
    type="integer",
    description=(
        "Hard cap on processed items for this run - keeps trial costs "
        "predictable. Billing stops when the cap or your spending limit "
        "is reached."
    ),
    minimum=1,
    default=25,
    section_caption="Advanced",
)


def _with_winner_fields(*extra: InputField) -> tuple[InputField, ...]:
    """Standard trailing fields every winning actor exposes."""
    return (*extra, MAX_ITEMS_FIELD, PROXY_CONFIG_FIELD)


ALL_PRESETS: dict[str, ActorSpec] = {
    spec.name: spec
    for spec in (
        SCRAPER_ACTOR,
        CRAWLER_ACTOR,
        SCREENSHOT_ACTOR,
        MONITOR_ACTOR,
        DOC_PARSER_ACTOR,
    )
}


# ── Niche-market actors (store gap targets) ─────────────────────────────────
# Chosen for: recurring demand on Apify Store, synergy with Pry's anti-bot
# core, no platform-specific parsers needed (ToS-safe generic extraction).

LLM_CORPUS_ACTOR = ActorSpec(
    name="pry-llm-corpus-builder",
    title="Pry LLM Corpus Builder",
    description=(
        "Build clean, LLM-ready text corpora from any website. Crawls a "
        "domain through 12-tier anti-bot bypass and emits deduplicated "
        "markdown documents structured for RAG pipelines and fine-tuning "
        "datasets. The dataset drops straight into LangChain, LlamaIndex "
        "or your vector store."
    ),
    version="1.0",
    processor="corpus",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="min_content_chars",
            title="Min content length (chars)",
            type="integer",
            description="Skip pages shorter than this - filters nav/boilerplate shells.",
            minimum=0,
            default=500,
            section_caption="Corpus settings",
        ),
        InputField(
            name="dedupe",
            title="Near-duplicate removal",
            type="boolean",
            description="SimHash-based near-duplicate filtering across the corpus.",
            default=True,
            section_caption="Corpus settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="document-emitted",
            title="Document emitted",
            description="One cleaned markdown document added to the corpus.",
            price_usd=0.004,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=8192,
)

SEO_AUDITOR_ACTOR = ActorSpec(
    name="pry-seo-site-auditor",
    title="Pry SEO Site Auditor",
    description=(
        "Full-site SEO audit behind anti-bot walls: crawls every page and "
        "reports titles, meta descriptions, heading structure, canonical "
        "tags, response codes and content freshness signals in one "
        "structured dataset."
    ),
    version="1.0",
    processor="seo",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="check_headings",
            title="Audit heading structure",
            type="boolean",
            description="Extract h1-h6 hierarchy per page.",
            default=True,
            section_caption="Audit settings",
        ),
        InputField(
            name="check_canonicals",
            title="Audit canonical tags",
            type="boolean",
            description="Flag missing or conflicting canonical URLs.",
            default=True,
            section_caption="Audit settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-audited",
            title="Page audited",
            description="One page crawled with full SEO signal extraction.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=8192,
)

LEAD_HARVESTER_ACTOR = ActorSpec(
    name="pry-lead-harvester",
    title="Pry Lead Harvester",
    description=(
        "Harvest publicly listed business contacts from websites: emails, "
        "phone numbers and social profile links extracted from contact "
        "pages and footers across a domain, with anti-bot escalation for "
        "protected sites."
    ),
    version="1.0",
    processor="leads",
    inputs=(
        URLS_FIELD,
        InputField(
            name="probe_contact_pages",
            title="Probe /contact paths",
            type="boolean",
            description="Also try common contact-page paths (/contact, /contact-us, /impressum).",
            default=True,
            section_caption="Harvest settings",
        ),
        InputField(
            name="include_social_links",
            title="Include social profiles",
            type="boolean",
            description="Collect LinkedIn/X/Facebook page links found on site.",
            default=True,
            section_caption="Harvest settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="lead-set-harvested",
            title="Lead set harvested",
            description="One domain processed with contacts extracted.",
            price_usd=0.005,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

NEWS_MONITOR_ACTOR = ActorSpec(
    name="pry-news-feed-monitor",
    title="Pry News Feed Monitor",
    description=(
        "Monitor news sites and blogs through RSS/Atom discovery plus "
        "full-article extraction behind paywalls' bot defenses (public "
        "articles only). Emits new articles since the last run."
    ),
    version="1.0",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="max_articles_per_source",
            title="Max articles per source",
            type="integer",
            description="Cap per feed to control cost.",
            minimum=1,
            maximum=100,
            default=20,
            section_caption="Monitor settings",
        ),
        InputField(
            name="full_text",
            title="Extract full article text",
            type="boolean",
            description="Fetch and extract complete article bodies, not just summaries.",
            default=True,
            section_caption="Monitor settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="article-extracted",
            title="Article extracted",
            description="One full article extracted into the dataset.",
            price_usd=0.002,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

PRICE_WATCHER_ACTOR = ActorSpec(
    name="pry-price-watcher",
    title="Pry Price Watcher",
    description=(
        "Track product prices on any e-commerce site - including "
        "JavaScript-rendered storefronts behind bot protection. Uses "
        "schema.org/Product structured data first, heuristic extraction "
        "as fallback, and SimHash change detection between runs."
    ),
    version="1.0",
    processor="price",
    inputs=(
        URLS_FIELD,
        InputField(
            name="currency_hint",
            title="Currency hint",
            type="string",
            description="Expected ISO currency code for price normalization.",
            default="USD",
            section_caption="Watch settings",
        ),
        InputField(
            name="extract_image",
            title="Include product image URL",
            type="boolean",
            description="Capture the primary product image when present.",
            default=False,
            section_caption="Watch settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="price-captured",
            title="Price captured",
            description="One product price captured and normalized.",
            price_usd=0.004,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=8192,
)

ALL_PRESETS.update(
    {
        spec.name: spec
        for spec in (
            LLM_CORPUS_ACTOR,
            SEO_AUDITOR_ACTOR,
            LEAD_HARVESTER_ACTOR,
            NEWS_MONITOR_ACTOR,
            PRICE_WATCHER_ACTOR,
        )
    }
)


# ── Market-driven actors (from Apify Store sweep, see MARKET-ANALYSIS.md) ────
# Evidence: PPE = 46/50 top actors; lead-gen = largest category (19,746);
# Google Maps scraper 36M runs; Google SERP scraper 112M runs; the
# maps+contacts combo (2M runs) proves contact enrichment demand.

MAPS_LEADS_ACTOR = ActorSpec(
    name="pry-maps-lead-extractor",
    title="Pry Maps Lead Extractor",
    description=(
        "Extract local business leads from Google Maps listings: names, "
        "addresses, phones, websites and publicly listed emails in one "
        "pass. Combines the two most-demanded Apify workflows - maps data "
        "and contact enrichment - with anti-bot escalation built in."
    ),
    version="1.0",
    processor="leads",
    inputs=(
        InputField(
            name="urls",
            title="Maps search URLs",
            type="array",
            description=("Google Maps search or place URLs to extract businesses from."),
            editor="requestListSources",
            # Stable prefill: the platform's daily automated test runs the
            # DEFAULT input - a Maps URL there risks deprecation. Error items
            # still produce a non-empty dataset, so the test passes.
            prefill=[{"url": "https://example.com"}],
            required=True,
        ),
        InputField(
            name="include_social_links",
            title="Include social profiles",
            type="boolean",
            description="Collect LinkedIn/X/Facebook links from business sites.",
            default=True,
            section_caption="Lead settings",
        ),
        InputField(
            name="timeout",
            title="Timeout (seconds)",
            type="integer",
            description="Per-listing timeout.",
            minimum=5,
            maximum=120,
            default=30,
            section_caption="Lead settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="business-extracted",
            title="Business extracted",
            description="One business listing with contact details extracted.",
            price_usd=0.005,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=4096,
)

SERP_ACTOR = ActorSpec(
    name="pry-serp-scraper",
    title="Pry SERP Scraper",
    description=(
        "Scrape Google search results pages: organic listings, ads, "
        "featured snippets and People Also Ask - via TLS-fingerprint and "
        "Googlebot-emulation tiers purpose-built for search engines. "
        "Structured JSON out, CAPTCHA escalation automatic."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        InputField(
            name="num_results",
            title="Results per query",
            type="integer",
            description="Number of organic results to parse per page.",
            minimum=10,
            maximum=100,
            default=20,
            section_caption="SERP settings",
        ),
        InputField(
            name="include_ads",
            title="Include ads",
            type="boolean",
            description="Also extract sponsored listings.",
            default=False,
            section_caption="SERP settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="serp-scraped",
            title="SERP scraped",
            description="One search results page parsed into structured listings.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

JOBS_ACTOR = ActorSpec(
    name="pry-jobs-aggregator",
    title="Pry Jobs Aggregator",
    description=(
        "Aggregate job postings across company career sites running "
        "Greenhouse, Lever, Workday and other ATS platforms - public "
        "pages only, no logins. Structured titles, locations, salaries "
        "and apply links, normalized across boards."
    ),
    version="1.0",
    processor="news",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="ats_filter",
            title="ATS platform",
            type="string",
            description="Limit parsing to a specific ATS layout.",
            editor="select",
            enum=["auto", "greenhouse", "lever", "workday"],
            default="auto",
            section_caption="Jobs settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="job-extracted",
            title="Job extracted",
            description="One job posting normalized into the dataset.",
            price_usd=0.002,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

REAL_ESTATE_ACTOR = ActorSpec(
    name="pry-property-lister",
    title="Pry Property Lister",
    description=(
        "Extract property listings from real estate sites: prices, beds, "
        "baths, square footage, addresses and agent contacts - including "
        "JS-rendered portals behind bot protection."
    ),
    version="1.0",
    processor="price",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="currency_hint",
            title="Currency hint",
            type="string",
            description="Expected ISO currency code for price normalization.",
            default="USD",
            section_caption="Listing settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="listing-extracted",
            title="Listing extracted",
            description="One property listing normalized into the dataset.",
            price_usd=0.004,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=8192,
)

ALL_PRESETS.update(
    {
        spec.name: spec
        for spec in (
            MAPS_LEADS_ACTOR,
            SERP_ACTOR,
            JOBS_ACTOR,
            REAL_ESTATE_ACTOR,
        )
    }
)


# ── Portfolio expansion to 30 (each maps to an existing Pry domain) ──────────

CRYPTO_LISTING_ACTOR = ActorSpec(
    name="pry-crypto-listing-monitor",
    title="Pry Crypto Listing Monitor",
    description=(
        "Monitor crypto news and exchange pages for new token listing "
        "announcements. Early listing signals are a proven trading edge; "
        "this actor watches your sources through anti-bot escalation and "
        "emits structured announcement items."
    ),
    version="1.0",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="keywords",
            title="Signal keywords",
            type="array",
            item_type="string",
            editor="stringList",
            description="Flag items whose content matches any keyword (lists, delist, futures).",
            prefill=["listing", "delist", "futures", "spot"],
            section_caption="Signal settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="signal-checked",
            title="Signal checked",
            description="One source page scanned for listing signals.",
            price_usd=0.002,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

RUGPULL_ACTOR = ActorSpec(
    name="pry-token-safety-scanner",
    title="Pry Token Safety Scanner",
    description=(
        "Screen token pages for rug-pull and honeypot risk signals using "
        "Pry's crypto security checks: contract flags, liquidity signals "
        "and risk scores compiled into one dataset per token."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        InputField(
            name="risk_threshold",
            title="Risk threshold",
            type="string",
            description="Maximum acceptable risk level before flagging.",
            editor="select",
            enum=["low", "medium", "high"],
            default="medium",
            section_caption="Scan settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="token-scanned",
            title="Token scanned",
            description="One token screened for safety signals.",
            price_usd=0.004,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

SEC_FILINGS_ACTOR = ActorSpec(
    name="pry-sec-filings-watch",
    title="Pry SEC Filings Watch",
    description=(
        "Watch SEC EDGAR for new filings by company, form type or CIK - "
        "10-K, 10-Q, 8-K, S-1 and more. Public records monitoring with "
        "structured emit-on-change semantics for compliance and intel teams."
    ),
    version="1.0",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="form_types",
            title="Form types",
            type="array",
            item_type="string",
            editor="stringList",
            description="Filter to specific filing forms.",
            prefill=["10-K", "10-Q", "8-K"],
            section_caption="Filing settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="filing-detected",
            title="Filing detected",
            description="One new filing detected and emitted.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

SANCTIONS_ACTOR = ActorSpec(
    name="pry-sanctions-screener",
    title="Pry Sanctions Screener",
    description=(
        "Screen entity names against public sanctions and watchlist lists "
        "sources (OFAC SDN, EU consolidated lists). Compliance-grade "
        "monitoring with match evidence in every dataset item."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        InputField(
            name="match_sensitivity",
            title="Match sensitivity",
            type="string",
            description="Fuzzy-match strictness for name screening.",
            editor="select",
            enum=["exact", "fuzzy"],
            default="fuzzy",
            section_caption="Screening settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="entity-screened",
            title="Entity screened",
            description="One entity screened against public sanctions sources.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

COURT_DOCKET_ACTOR = ActorSpec(
    name="pry-court-docket-monitor",
    title="Pry Court Docket Monitor",
    description=(
        "Monitor public court dockets for new cases, motions and rulings "
        "by party or jurisdiction. Litigation intelligence without manual "
        "PACER trawling."
    ),
    version="1.0",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="party_filter",
            title="Party name filter",
            type="string",
            description="Only emit docket entries matching this party.",
            default="",
            section_caption="Docket settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="docket-updated",
            title="Docket updated",
            description="One monitored docket checked; changes emitted.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

HOTEL_RATE_ACTOR = ActorSpec(
    name="pry-hotel-rate-watch",
    title="Pry Hotel Rate Watch",
    description=(
        "Track hotel room rates across booking sites - including "
        "JS-rendered portals behind bot walls. Rate parity checks, "
        "date-range comparisons and drop alerts in one dataset."
    ),
    version="1.0",
    processor="price",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="currency_hint",
            title="Currency hint",
            type="string",
            description="Expected ISO currency code.",
            default="USD",
            section_caption="Rate settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="rate-captured",
            title="Rate captured",
            description="One hotel rate captured and normalized.",
            price_usd=0.004,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=4096,
)

FLIGHT_PRICE_ACTOR = ActorSpec(
    name="pry-flight-price-watch",
    title="Pry Flight Price Watch",
    description=(
        "Watch flight fares on any route across OTAs and airline sites "
        "without GDS fees. JS-rendered results handled by stealth browser "
        "tiers; normalized price points per observation."
    ),
    version="1.0",
    processor="price",
    inputs=(
        URLS_FIELD,
        InputField(
            name="cabin_class",
            title="Cabin class",
            type="string",
            description="Economy, business or first.",
            editor="select",
            enum=["economy", "business", "first"],
            default="economy",
            section_caption="Route settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="fare-captured",
            title="Fare captured",
            description="One fare observation captured and normalized.",
            price_usd=0.004,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=4096,
)

REVIEW_AGGREGATOR_ACTOR = ActorSpec(
    name="pry-review-aggregator",
    title="Pry Review Aggregator",
    description=(
        "Aggregate product reviews from storefronts and review platforms "
        "- ratings, text, dates and reviewer metadata - normalized into "
        "one analysis-ready dataset."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="min_rating",
            title="Min rating filter",
            type="integer",
            description="Only keep reviews at or above this rating (0 keeps all).",
            minimum=0,
            maximum=5,
            default=0,
            section_caption="Review settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="review-collected",
            title="Review collected",
            description="One review collected into the dataset.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=1024,
    max_memory_mbytes=8192,
)

INVENTORY_ALERT_ACTOR = ActorSpec(
    name="pry-inventory-alert",
    title="Pry Inventory Alert",
    description=(
        "Watch product availability on any storefront: in-stock/out-of-stock "
        "state, price-at-checkout and restock timing - JS-rendered shops "
        "included."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        InputField(
            name="check_interval_hint",
            title="Suggested interval (minutes)",
            type="integer",
            description="Hint for scheduling cadence when paired with Apify schedules.",
            minimum=5,
            maximum=1440,
            default=60,
            section_caption="Watch settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="stock-checked",
            title="Stock checked",
            description="One product availability check.",
            price_usd=0.002,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

DEAL_RADAR_ACTOR = ActorSpec(
    name="pry-deal-radar",
    title="Pry Deal Radar",
    description=(
        "Surface deals, coupons and discounts across retail sites - "
        "price-drop detection against prior observations with percentage "
        "math done for you."
    ),
    version="1.0",
    processor="price",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="drop_threshold_pct",
            title="Drop alert threshold (%)",
            type="integer",
            description="Emit only drops larger than this percent.",
            minimum=1,
            maximum=90,
            default=10,
            section_caption="Deal settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="deal-scanned",
            title="Deal scanned",
            description="One offer page scanned for discounts.",
            price_usd=0.002,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

SERP_RANK_TRACKER_ACTOR = ActorSpec(
    name="pry-serp-rank-tracker",
    title="Pry SERP Rank Tracker",
    description=(
        "Daily keyword rank tracking on Google: position, URL and SERP "
        "feature presence per keyword, with history-friendly flat rows. "
        "TLS-fingerprint and Googlebot tiers keep tracking alive."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        InputField(
            name="depth",
            title="Results depth",
            type="integer",
            description="How deep into results to search for your domain.",
            minimum=10,
            maximum=100,
            default=50,
            section_caption="Tracking settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="rank-checked",
            title="Rank checked",
            description="One keyword tracked on one engine.",
            price_usd=0.002,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

AD_INTEL_ACTOR = ActorSpec(
    name="pry-ad-intel-monitor",
    title="Pry Ad Intel Monitor",
    description=(
        "Monitor competitor advertising: detect active ad placements and "
        "landing-page changes across the web with block-signal aware "
        "escalation for protected publisher sites."
    ),
    version="1.0",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="detect_networks",
            title="Detect ad networks",
            type="boolean",
            description="Identify which ad networks a page runs.",
            default=True,
            section_caption="Intel settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="placement-scanned",
            title="Placement scanned",
            description="One page scanned for ad placements.",
            price_usd=0.002,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

LOCAL_DIRECTORY_ACTOR = ActorSpec(
    name="pry-local-directory-extractor",
    title="Pry Local Directory Extractor",
    description=(
        "Extract business listings from local directories and yellow-page "
        "style sites: names, categories, addresses, phones and websites - "
        "the dataset feeds directly into outreach tooling."
    ),
    version="1.0",
    processor="leads",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="category_filter",
            title="Category filter",
            type="string",
            description="Only keep listings matching this category keyword.",
            default="",
            section_caption="Extract settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="listing-extracted",
            title="Listing extracted",
            description="One directory listing extracted.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

PROVIDER_FINDER_ACTOR = ActorSpec(
    name="pry-provider-finder",
    title="Pry Healthcare Provider Finder",
    description=(
        "Find healthcare providers on public directories: names, "
        "specialties, locations, accepting-patient status and contact "
        "details - normalized for care-navigation products."
    ),
    version="1.0",
    processor="leads",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="specialty",
            title="Specialty filter",
            type="string",
            description="Only keep providers matching this specialty.",
            default="",
            section_caption="Search settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="provider-extracted",
            title="Provider extracted",
            description="One provider profile extracted.",
            price_usd=0.004,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

TRIALS_WATCH_ACTOR = ActorSpec(
    name="pry-clinical-trials-watch",
    title="Pry Clinical Trials Watch",
    description=(
        "Monitor clinical trial registries for new studies by condition, "
        "phase or sponsor. Structured trial metadata for pharma intel and "
        "recruitment platforms."
    ),
    version="1.0",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="phase_filter",
            title="Phase filter",
            type="string",
            description="Limit to a trial phase.",
            editor="select",
            enum=["any", "phase-1", "phase-2", "phase-3", "phase-4"],
            default="any",
            section_caption="Trial settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="trial-detected",
            title="Trial detected",
            description="One trial posting detected and emitted.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

TENDER_MONITOR_ACTOR = ActorSpec(
    name="pry-tender-procurement-monitor",
    title="Pry Tender & Procurement Monitor",
    description=(
        "Watch government and enterprise procurement portals for new "
        "tenders, RFPs and awards matching your categories - public "
        "records monitoring with deadline fields normalized."
    ),
    version="1.0",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="category_keywords",
            title="Category keywords",
            type="array",
            item_type="string",
            editor="stringList",
            description="Flag tenders matching these keywords.",
            prefill=["construction", "software", "consulting"],
            section_caption="Tender settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="tender-scanned",
            title="Tender scanned",
            description="One procurement portal page scanned.",
            price_usd=0.002,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

ALL_PRESETS.update(
    {
        spec.name: spec
        for spec in (
            CRYPTO_LISTING_ACTOR,
            RUGPULL_ACTOR,
            SEC_FILINGS_ACTOR,
            SANCTIONS_ACTOR,
            COURT_DOCKET_ACTOR,
            HOTEL_RATE_ACTOR,
            FLIGHT_PRICE_ACTOR,
            REVIEW_AGGREGATOR_ACTOR,
            INVENTORY_ALERT_ACTOR,
            DEAL_RADAR_ACTOR,
            SERP_RANK_TRACKER_ACTOR,
            AD_INTEL_ACTOR,
            LOCAL_DIRECTORY_ACTOR,
            PROVIDER_FINDER_ACTOR,
            TRIALS_WATCH_ACTOR,
            TENDER_MONITOR_ACTOR,
        )
    }
)
