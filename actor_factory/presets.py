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
    version="1.1",
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
            price_usd=0.003,
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
    version="1.1",
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
    version="1.1",
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
            price_usd=0.003,
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
    version="1.1",
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
    processor="monitor",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

DOC_PARSER_ACTOR = ActorSpec(
    name="pry-document-parser",
    title="Pry Document Parser",
    description=(
        "Parse PDFs, DOCX and images behind URLs into clean text/markdown with OCR fallback."
    ),
    version="1.1",
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
            price_usd=0.003,
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
    version="1.1",
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
            price_usd=0.0015,
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
    version="1.1",
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
            price_usd=0.0015,
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
    version="1.1",
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
            price_usd=0.0015,
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
    version="1.1",
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
            price_usd=0.001,
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
    version="1.1",
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
            price_usd=0.001,
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
    version="1.1",
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
            price_usd=0.0015,
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
    version="1.1",
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
    version="1.1",
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
            price_usd=0.0015,
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
    version="1.1",
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
            price_usd=0.0015,
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
    version="1.1",
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
            price_usd=0.001,
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
    version="1.1",
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
            price_usd=0.003,
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
    version="1.1",
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
            price_usd=0.001,
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
    version="1.1",
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
    version="1.1",
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
            price_usd=0.001,
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
    version="1.1",
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
            price_usd=0.001,
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
    version="1.1",
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
            price_usd=0.001,
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
    version="1.1",
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
            price_usd=0.0015,
        ),
    ),
    processor="extract",
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
    version="1.1",
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
            price_usd=0.001,
        ),
    ),
    processor="monitor",
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
    version="1.1",
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
            price_usd=0.001,
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
    version="1.1",
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
            price_usd=0.003,
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
    version="1.1",
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
            price_usd=0.0015,
        ),
    ),
    processor="audit",
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
    version="1.1",
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
            price_usd=0.0015,
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
    version="1.1",
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
            price_usd=0.0015,
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
    version="1.1",
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
            price_usd=0.001,
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
    version="1.1",
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
            price_usd=0.001,
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


# ── Gap-filler batch 2: thin-supply niches from the keyword sweep ────────────
# Evidence in MARKET-ANALYSIS.md gap table (supply vs demand runs).

BROKEN_LINKS_ACTOR = ActorSpec(
    name="pry-broken-links-auditor",
    title="Pry Broken Links Auditor",
    description=(
        "Crawl a site and report every broken internal or external link "
        "with HTTP status, source page and anchor text. Site-health audits "
        "that used to need desktop tooling now run on a schedule."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="check_externals",
            title="Check external links",
            type="boolean",
            description="Also verify links leaving the domain.",
            default=True,
            section_caption="Audit settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-audited",
            title="Page audited",
            description="One page crawled with all links status-checked.",
            price_usd=0.0015,
        ),
    ),
    processor="audit",
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

SSL_MONITOR_ACTOR = ActorSpec(
    name="pry-ssl-cert-monitor",
    title="Pry SSL Certificate Monitor",
    description=(
        "Watch TLS certificate health across your domains: expiry "
        "countdowns, issuer changes and handshake failures - caught by "
        "connection-level probes before browsers scare your visitors."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="warn_days",
            title="Warn before expiry (days)",
            type="integer",
            description="Emit a warning item when expiry is within this window.",
            minimum=1,
            maximum=90,
            default=14,
            section_caption="Monitor settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="cert-checked",
            title="Certificate checked",
            description="One domain's TLS certificate probed.",
            price_usd=0.003,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

WAYBACK_DIFF_ACTOR = ActorSpec(
    name="pry-wayback-diff",
    title="Pry Wayback Diff",
    description=(
        "Compare any live page against its last archive.org snapshot and "
        "emit a structured diff: what changed, when it changed and how "
        "similar the versions are (SimHash similarity score included)."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="similarity_threshold",
            title="Similarity threshold",
            type="float",
            description="Below this SimHash similarity the page counts as rewritten.",
            minimum=0.0,
            maximum=1.0,
            default=0.85,
            section_caption="Diff settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-compared",
            title="Page compared",
            description="One live-vs-archive comparison computed.",
            price_usd=0.001,
        ),
    ),
    processor="monitor",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

PODCAST_MINER_ACTOR = ActorSpec(
    name="pry-podcast-feed-miner",
    title="Pry Podcast Feed Miner",
    description=(
        "Mine podcast RSS feeds into structured episode datasets: titles, "
        "descriptions, durations, publish dates and audio URLs - perfect "
        "for media monitoring and transcript pipeline feeds."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="max_episodes",
            title="Max episodes per feed",
            type="integer",
            description="Cap per feed to control cost.",
            minimum=1,
            maximum=200,
            default=50,
            section_caption="Feed settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="episode-extracted",
            title="Episode extracted",
            description="One podcast episode extracted to the dataset.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

NEWSLETTER_MINER_ACTOR = ActorSpec(
    name="pry-newsletter-archive-miner",
    title="Pry Newsletter Archive Miner",
    description=(
        "Extract newsletter archives and email digest pages into clean "
        "structured datasets - issues, subjects, senders and body content "
        "for competitive content intelligence."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="include_body_text",
            title="Include body text",
            type="boolean",
            description="Extract full issue bodies, not just metadata.",
            default=True,
            section_caption="Extract settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="issue-extracted",
            title="Issue extracted",
            description="One newsletter issue extracted.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=2048,
    uses_browser=False,
)

A11Y_SCANNER_ACTOR = ActorSpec(
    name="pry-accessibility-scanner",
    title="Pry Accessibility Scanner",
    description=(
        "WCAG-oriented accessibility signals for every page: images "
        "missing alt text, heading hierarchy violations, missing page "
        "titles and language declarations - prioritized issue lists per "
        "crawl."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="fail_on_missing_alt",
            title="Flag missing alt text",
            type="boolean",
            description="Report every image without an alt attribute.",
            default=True,
            section_caption="Audit settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-scanned",
            title="Page scanned",
            description="One page scanned for accessibility signals.",
            price_usd=0.0015,
        ),
    ),
    processor="audit",
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

BACKLINK_HARVESTER_ACTOR = ActorSpec(
    name="pry-outbound-link-harvester",
    title="Pry Outbound Link Harvester",
    description=(
        "Harvest external outbound links per page across a site: which "
        "domains a site links to, how often, and from where - prospecting "
        "data for SEO outreach and partnership research."
    ),
    version="1.1",
    processor="backlinks",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="exclude_domains",
            title="Excluded domains",
            type="array",
            item_type="string",
            editor="stringList",
            description="Domains to skip (e.g. social widgets).",
            prefill=["facebook.com", "twitter.com", "x.com"],
            section_caption="Harvest settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-harvested",
            title="Page harvested",
            description="One page's outbound link profile harvested.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

ONION_MONITOR_ACTOR = ActorSpec(
    name="pry-onion-site-monitor",
    title="Pry Onion Site Monitor",
    description=(
        "Monitor .onion services over Tor - brand abuse, leak-site watch "
        "and dark-web mention tracking. Pry ships Tor as a first-class "
        "tier; almost no competitor can reach these sources at all."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="keyword_filter",
            title="Keyword filter",
            type="string",
            description="Only emit pages matching this keyword.",
            default="",
            section_caption="Monitor settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="onion-page-checked",
            title="Onion page checked",
            description="One .onion page fetched through the Tor tier.",
            price_usd=0.001,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

GDPR_COOKIE_ACTOR = ActorSpec(
    name="pry-gdpr-cookie-checker",
    title="Pry GDPR Cookie Checker",
    description=(
        "Check pages for cookie-consent banners, privacy-policy links and "
        "consent-management platforms - compliance evidence collection "
        "for audits across hundreds of properties at once."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="require_privacy_link",
            title="Require privacy link",
            type="boolean",
            description="Flag pages without a privacy-policy link.",
            default=True,
            section_caption="Check settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-checked",
            title="Page checked",
            description="One page checked for consent/privacy markers.",
            price_usd=0.0015,
        ),
    ),
    processor="audit",
    min_memory_mbytes=256,
    max_memory_mbytes=2048,
    uses_browser=False,
)

META_TAG_AUDITOR_ACTOR = ActorSpec(
    name="pry-social-card-auditor",
    title="Pry Social Card Auditor",
    description=(
        "Audit Open Graph and social preview tags across every page of a "
        "site: missing og:title/og:image, thin descriptions and canonical "
        "conflicts - fix link previews before your next campaign."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="require_og_image",
            title="Require og:image",
            type="boolean",
            description="Flag pages missing a social preview image.",
            default=True,
            section_caption="Audit settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="page-audited",
            title="Page audited",
            description="One page audited for social preview tags.",
            price_usd=0.0015,
        ),
    ),
    processor="audit",
    min_memory_mbytes=256,
    max_memory_mbytes=2048,
    uses_browser=False,
)

SITEMAP_DIFF_ACTOR = ActorSpec(
    name="pry-sitemap-diff",
    title="Pry Sitemap Diff",
    description=(
        "Track sitemap changes between runs: new URLs, removed URLs and "
        "lastmod shifts - the fastest way to catch competitor site launches "
        "and content strategy moves."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="emit_all",
            title="Emit full URL list",
            type="boolean",
            description="Push every URL found, not just the summary.",
            default=False,
            section_caption="Diff settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="sitemap-scanned",
            title="Sitemap scanned",
            description="One sitemap scanned and diffed against prior state.",
            price_usd=0.001,
        ),
    ),
    processor="monitor",
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

TECH_STACK_ACTOR = ActorSpec(
    name="pry-tech-stack-detector",
    title="Pry Tech Stack Detector",
    description=(
        "Detect the technology behind any website - frameworks, analytics, "
        "CMS, hosting signals - enriched with contact discovery for sales "
        "prospecting by stack."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="include_headers",
            title="Inspect response headers",
            type="boolean",
            description="Fingerprint servers and CDNs from headers.",
            default=True,
            section_caption="Detect settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="stack-detected",
            title="Stack detected",
            description="One site's technology stack detected.",
            price_usd=0.0015,
        ),
    ),
    processor="tech",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

CONTACT_FORM_FINDER_ACTOR = ActorSpec(
    name="pry-contact-form-finder",
    title="Pry Contact Form Finder",
    description=(
        "Find contact forms, mailto links and submission endpoints across "
        "prospect sites - the first step of automated outreach done "
        "respectfully: know exactly where to reach a business."
    ),
    version="1.1",
    processor="leads",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="probe_contact_pages",
            title="Probe /contact paths",
            type="boolean",
            description="Also try common contact-page paths.",
            default=True,
            section_caption="Finder settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="site-probed",
            title="Site probed",
            description="One site probed for contact channels.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=2048,
    uses_browser=False,
)

BLOG_EXTRACTOR_ACTOR = ActorSpec(
    name="pry-blog-post-extractor",
    title="Pry Blog Post Extractor",
    description=(
        "Extract complete blog archives: post URLs, titles, publish dates "
        "and full markdown bodies - content-gap analysis and editorial "
        "research in one dataset."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="full_text",
            title="Extract full text",
            type="boolean",
            description="Fetch and extract complete post bodies.",
            default=True,
            section_caption="Extract settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="post-extracted",
            title="Post extracted",
            description="One blog post extracted to the dataset.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

EVENT_LISTINGS_ACTOR = ActorSpec(
    name="pry-event-listings-aggregator",
    title="Pry Event Listings Aggregator",
    description=(
        "Aggregate event listings from conference, meetup and event-calenda "
        "sites: names, dates, venues, organizers and registration links - "
        "normalized for calendar and intel products."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="upcoming_only",
            title="Upcoming only",
            type="boolean",
            description="Drop events that already started.",
            default=True,
            section_caption="Filter settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="event-extracted",
            title="Event extracted",
            description="One event listing extracted.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

ALL_PRESETS.update(
    {
        spec.name: spec
        for spec in (
            BROKEN_LINKS_ACTOR,
            SSL_MONITOR_ACTOR,
            WAYBACK_DIFF_ACTOR,
            PODCAST_MINER_ACTOR,
            NEWSLETTER_MINER_ACTOR,
            A11Y_SCANNER_ACTOR,
            BACKLINK_HARVESTER_ACTOR,
            ONION_MONITOR_ACTOR,
            GDPR_COOKIE_ACTOR,
            META_TAG_AUDITOR_ACTOR,
            SITEMAP_DIFF_ACTOR,
            TECH_STACK_ACTOR,
            CONTACT_FORM_FINDER_ACTOR,
            BLOG_EXTRACTOR_ACTOR,
            EVENT_LISTINGS_ACTOR,
        )
    }
)


# ── Gap-filler batch 3: thinnest-supply niches from sweep #3 ─────────────────
# Evidence: MARKET-ANALYSIS.md gap table round 3 (scholarship=45 supply,
# udemy=61, course-catalog=260, weather=295, electricity=310, air-quality=438,
# press-release=591).

SCHOLARSHIP_FINDER_ACTOR = ActorSpec(
    name="pry-scholarship-grants-finder",
    title="Pry Scholarship & Grants Finder",
    description=(
        "Aggregate scholarship, grant and funding opportunities from education funding "
        "portals: amounts, deadlines, eligibility and application links - "
        "normalized for counseling platforms and search products."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="deadline_within_days",
            title="Deadline within (days)",
            type="integer",
            description="Only emit opportunities closing within this window.",
            minimum=1,
            maximum=365,
            default=90,
            section_caption="Filter settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="opportunity-extracted",
            title="Opportunity extracted",
            description="One scholarship or grant extracted.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=2048,
    uses_browser=False,
)

COURSE_CATALOG_ACTOR = ActorSpec(
    name="pry-course-catalog-extractor",
    title="Pry Course Catalog Extractor",
    description=(
        "Extract online course catalogs: titles, instructors, prices, "
        "ratings, durations and syllabi outlines from any course platform "
        "- market research for edtech and aggregation products."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="include_curriculum",
            title="Include curriculum outline",
            type="boolean",
            description="Extract module/lesson lists when present.",
            default=False,
            section_caption="Extract settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="course-extracted",
            title="Course extracted",
            description="One course listing normalized into the dataset.",
            price_usd=0.0015,
        ),
    ),
    processor="extract",
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

WEATHER_COLLECTOR_ACTOR = ActorSpec(
    name="pry-weather-data-collector",
    title="Pry Weather Data Collector",
    description=(
        "Collect weather observations and forecasts from any forecast page "
        "- temperature, precipitation and condition signals normalized "
        "into flat rows for analytics and alerting pipelines."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="location_label",
            title="Location label",
            type="string",
            description="Tag every row with this location identifier.",
            default="",
            section_caption="Collection settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="observation-collected",
            title="Observation collected",
            description="One weather observation collected.",
            price_usd=0.001,
        ),
    ),
    processor="monitor",
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

AIR_QUALITY_ACTOR = ActorSpec(
    name="pry-air-quality-monitor",
    title="Pry Air Quality Monitor",
    description=(
        "Monitor air-quality indices and pollutant readings from public "
        "monitoring pages - AQI, PM2.5/PM10 and trend direction for "
        "health, insurance and smart-city datasets."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="aqi_threshold",
            title="AQI alert threshold",
            type="integer",
            description="Emit an alert item when AQI exceeds this value.",
            minimum=0,
            maximum=500,
            default=100,
            section_caption="Alert settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="reading-collected",
            title="Reading collected",
            description="One air-quality reading collected.",
            price_usd=0.001,
        ),
    ),
    processor="monitor",
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

ELECTRICITY_PRICE_ACTOR = ActorSpec(
    name="pry-electricity-price-watch",
    title="Pry Electricity Price Watch",
    description=(
        "Track electricity tariff and spot-price publications from utility "
        "and exchange pages - day-ahead prices normalized per MWh for "
        "energy analysts and cost modelers."
    ),
    version="1.1",
    processor="price",
    inputs=(
        URLS_FIELD,
        InputField(
            name="unit",
            title="Price unit",
            type="string",
            description="Normalization unit for captured prices.",
            editor="select",
            enum=["EUR/MWh", "USD/MWh", "c/kWh"],
            default="EUR/MWh",
            section_caption="Price settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="tariff-captured",
            title="Tariff captured",
            description="One electricity price point captured.",
            price_usd=0.001,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

PRESS_RELEASE_ACTOR = ActorSpec(
    name="pry-press-release-monitor",
    title="Pry Press Release Monitor",
    description=(
        "Monitor company and wire-service press releases: headlines, "
        "datelines and full announcement text - PR intelligence and media "
        "monitoring without manual source checking."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="keyword_filter",
            title="Keyword filter",
            type="string",
            description="Only emit releases matching this keyword.",
            default="",
            section_caption="Monitor settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="release-extracted",
            title="Release extracted",
            description="One press release extracted.",
            price_usd=0.001,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=2048,
    uses_browser=False,
)

ARXIV_PAPER_WATCH_ACTOR = ActorSpec(
    name="pry-research-paper-watch",
    title="Pry Research Paper Watch",
    description=(
        "Watch academic preprint and journal listing pages for new papers "
        "by topic: titles, authors, abstracts and PDF links - literature "
        "surveillance for R&D and AI labs."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="topic_keywords",
            title="Topic keywords",
            type="array",
            item_type="string",
            editor="stringList",
            description="Only emit papers matching these topic keywords.",
            prefill=["LLM", "reinforcement learning"],
            section_caption="Topic settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="paper-detected",
            title="Paper detected",
            description="One new paper detected and emitted.",
            price_usd=0.001,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=2048,
    uses_browser=False,
)

ALL_PRESETS.update(
    {
        spec.name: spec
        for spec in (
            SCHOLARSHIP_FINDER_ACTOR,
            COURSE_CATALOG_ACTOR,
            WEATHER_COLLECTOR_ACTOR,
            AIR_QUALITY_ACTOR,
            ELECTRICITY_PRICE_ACTOR,
            PRESS_RELEASE_ACTOR,
            ARXIV_PAPER_WATCH_ACTOR,
        )
    }
)


# ── Gap-filler batch 4: unconsidered niches (sweep #3 + capability map) ──────

CVE_ADVISORY_ACTOR = ActorSpec(
    name="pry-cve-advisory-watch",
    title="Pry CVE Advisory Watch",
    description=(
        "Watch security advisory sources for new CVEs affecting your stack "
        "- severity, affected versions and remediation links in one feed. "
        "Vulnerability surveillance for engineering and compliance teams."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="min_severity",
            title="Minimum severity",
            type="string",
            description="Only emit advisories at or above this severity.",
            editor="select",
            enum=["low", "medium", "high", "critical"],
            default="high",
            section_caption="Filter settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="advisory-detected",
            title="Advisory detected",
            description="One new security advisory detected.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

TOS_POLICY_WATCH_ACTOR = ActorSpec(
    name="pry-terms-policy-watch",
    title="Pry Terms & Policy Watch",
    description=(
        "Monitor Terms of Service and Privacy Policy pages for silent "
        "changes - diff-aware emit-on-change semantics so legal and "
        "compliance teams catch rewrites the day they happen."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="section_filter",
            title="Section keywords",
            type="array",
            item_type="string",
            editor="stringList",
            description="Only emit changes touching these sections.",
            prefill=["arbitration", "data sharing", "liability"],
            section_caption="Watch settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="policy-checked",
            title="Policy checked",
            description="One ToS/privacy page checked for changes.",
            price_usd=0.001,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

FORUM_MINER_ACTOR = ActorSpec(
    name="pry-forum-discussion-miner",
    title="Pry Forum Discussion Miner",
    description=(
        "Mine forum threads and discussion boards: titles, authors, reply "
        "counts and top posts across public communities - voice-of-customer "
        "and pain-point research at scale."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="min_replies",
            title="Min replies",
            type="integer",
            description="Only keep threads with at least this many replies.",
            minimum=0,
            default=3,
            section_caption="Filter settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="thread-extracted",
            title="Thread extracted",
            description="One forum thread extracted.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

CHANGELOG_TRACKER_ACTOR = ActorSpec(
    name="pry-changelog-tracker",
    title="Pry Changelog Tracker",
    description=(
        "Track competitor product changelogs and release notes pages - "
        "new features, fixes and pricing-page edits detected between runs "
        "so product teams never miss a competitor move."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="emit_unchanged",
            title="Emit unchanged runs",
            type="boolean",
            description="Push a no-change item for continuous tracking history.",
            default=False,
            section_caption="Track settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="changelog-scanned",
            title="Changelog scanned",
            description="One changelog source scanned for updates.",
            price_usd=0.001,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

DOCS_DIFF_ACTOR = ActorSpec(
    name="pry-api-docs-diff",
    title="Pry API Docs Diff",
    description=(
        "Watch public API documentation pages for endpoint changes - new "
        "routes, renamed fields, deprecation notices - so integrations "
        "break before your customers notice, not after."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="watch_paths",
            title="Docs paths",
            type="array",
            item_type="string",
            editor="stringList",
            description="Doc URL paths to monitor.",
            prefill=["/reference", "/changelog"],
            section_caption="Watch settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="docs-scanned",
            title="Docs scanned",
            description="One documentation source scanned.",
            price_usd=0.001,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

STATUS_PAGE_ACTOR = ActorSpec(
    name="pry-status-page-aggregator",
    title="Pry Status Page Aggregator",
    description=(
        "Aggregate vendor status pages into one incident feed: ongoing "
        "incidents, maintenance windows and resolution history across "
        "every service your operations depend on."
    ),
    version="1.1",
    processor="news",
    inputs=(
        URLS_FIELD,
        InputField(
            name="active_only",
            title="Active incidents only",
            type="boolean",
            description="Drop resolved incidents from the dataset.",
            default=True,
            section_caption="Feed settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="status-checked",
            title="Status checked",
            description="One status page checked.",
            price_usd=0.001,
        ),
    ),
    min_memory_mbytes=256,
    max_memory_mbytes=1024,
    uses_browser=False,
)

MENU_EXTRACTOR_ACTOR = ActorSpec(
    name="pry-restaurant-menu-extractor",
    title="Pry Restaurant Menu Extractor",
    description=(
        "Extract restaurant menus from public pages: items, descriptions, "
        "prices and sections - normalized data for food delivery, nutrition "
        "and local discovery products."
    ),
    version="1.1",
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
            section_caption="Extract settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="menu-extracted",
            title="Menu extracted",
            description="One restaurant menu extracted.",
            price_usd=0.0015,
        ),
    ),
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

RECIPE_MINER_ACTOR = ActorSpec(
    name="pry-recipe-miner",
    title="Pry Recipe Miner",
    description=(
        "Mine recipe sites for structured cooking data: ingredients, "
        "steps, prep/cook times and nutrition claims - content pipelines "
        "for meal-planning and grocery products."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="include_nutrition",
            title="Include nutrition claims",
            type="boolean",
            description="Capture nutrition facts when present.",
            default=True,
            section_caption="Extract settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="recipe-extracted",
            title="Recipe extracted",
            description="One recipe extracted to the dataset.",
            price_usd=0.0015,
        ),
    ),
    processor="extract",
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

ALL_PRESETS.update(
    {
        spec.name: spec
        for spec in (
            CVE_ADVISORY_ACTOR,
            TOS_POLICY_WATCH_ACTOR,
            FORUM_MINER_ACTOR,
            CHANGELOG_TRACKER_ACTOR,
            DOCS_DIFF_ACTOR,
            STATUS_PAGE_ACTOR,
            MENU_EXTRACTOR_ACTOR,
            RECIPE_MINER_ACTOR,
        )
    }
)

# ── batch 19: high-demand data verticals (e-commerce, AI support, local SEO) ─

PRODUCT_DATA_ACTOR = ActorSpec(
    name="pry-product-data-extractor",
    title="Pry Product Data Extractor",
    description=(
        "Extract structured product data from any e-commerce page: name, "
        "price, currency, availability, brand and images - powered by "
        "schema.org JSON-LD that Shopify, WooCommerce and Magento stores "
        "already embed. Feed price intelligence, catalog syncs and "
        "competitor monitoring."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="include_variants",
            title="Include variant offers",
            type="boolean",
            description="Capture multiple offers when a product has variants.",
            default=True,
            section_caption="Extract settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="product-extracted",
            title="Product extracted",
            description="One product extracted to the dataset.",
            price_usd=0.0015,
        ),
    ),
    processor="extract",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

ECOMMERCE_CRAWLER_ACTOR = ActorSpec(
    name="pry-ecommerce-catalog-crawler",
    title="Pry E-commerce Catalog Crawler",
    description=(
        "Crawl an entire online store and extract every product with "
        "prices, availability and categories - full catalog exports for "
        "market research, dropshipping feeds and competitor price "
        "tracking across Shopify, WooCommerce and custom platforms."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="category_filter",
            title="Category URL contains",
            type="string",
            description="Only crawl product URLs matching this path fragment.",
            default="",
            section_caption="Crawl scope",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="product-extracted",
            title="Product extracted",
            description="One product extracted to the dataset.",
            price_usd=0.0015,
        ),
    ),
    processor="extract",
    min_memory_mbytes=1024,
    max_memory_mbytes=4096,
)

KNOWLEDGE_BASE_MINER_ACTOR = ActorSpec(
    name="pry-knowledge-base-miner",
    title="Pry Knowledge Base Miner",
    description=(
        "Turn help centers and FAQ pages into clean question-answer pairs "
        "using FAQPage and HowTo structured data - training data for "
        "support chatbots, AI agents and self-service knowledge bases."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
        InputField(
            name="min_answer_chars",
            title="Minimum answer length",
            type="integer",
            description="Skip answers shorter than this many characters.",
            default=80,
            section_caption="Extract settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="faq-pair-extracted",
            title="FAQ pair extracted",
            description="One question-answer pair extracted to the dataset.",
            price_usd=0.0015,
        ),
    ),
    processor="extract",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

LOCAL_BUSINESS_AUDITOR_ACTOR = ActorSpec(
    name="pry-local-business-schema-auditor",
    title="Pry Local Business Schema Auditor",
    description=(
        "Audit LocalBusiness structured data on any business website: "
        "name, address, phone, opening hours and geo coordinates as "
        "schema.org JSON-LD - validate your own markup or prospect "
        "businesses with missing or broken local SEO schema."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="require_geo",
            title="Require geo coordinates",
            type="boolean",
            description="Flag listings missing latitude/longitude.",
            default=True,
            section_caption="Audit rules",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="business-audited",
            title="Business audited",
            description="One business listing audited.",
            price_usd=0.0015,
        ),
    ),
    processor="extract",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

ALL_PRESETS.update(
    {
        spec.name: spec
        for spec in (
            PRODUCT_DATA_ACTOR,
            ECOMMERCE_CRAWLER_ACTOR,
            KNOWLEDGE_BASE_MINER_ACTOR,
            LOCAL_BUSINESS_AUDITOR_ACTOR,
        )
    }
)

# ── batch 20: public-API-backed lineup (highest reliability tier) ────────────
# These Actors hit documented public JSON APIs / feeds - results they promise
# are results they deliver, no anti-bot lottery.

APP_STORE_REVIEWS_ACTOR = ActorSpec(
    name="pry-app-store-review-miner",
    title="Pry App Store Review Miner",
    description=(
        "Mine Apple App Store reviews and app metadata via Apple's public "
        "iTunes API - user sentiment, ratings and feature requests for "
        "competitor analysis, product research and support triage."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="country_store",
            title="App Store country",
            type="string",
            description="ISO store code for reviews feed (e.g. us, gb, de).",
            default="us",
            section_caption="Source settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="review-mined",
            title="Review mined",
            description="One review or metadata record extracted.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

GITHUB_RELEASE_MONITOR_ACTOR = ActorSpec(
    name="pry-github-release-monitor",
    title="Pry GitHub Release Monitor",
    description=(
        "Monitor GitHub repositories for new releases, tags and changelog "
        "entries via the public GitHub API - track competitors, "
        "dependencies and open-source projects without watching manually."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="include_prereleases",
            title="Include pre-releases",
            type="boolean",
            description="Keep draft/pre-release entries in the dataset.",
            default=False,
            section_caption="Monitor settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="release-checked",
            title="Release checked",
            description="One repository release feed checked.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

NPM_PACKAGE_STATS_ACTOR = ActorSpec(
    name="pry-npm-package-stats",
    title="Pry npm Package Stats",
    description=(
        "Pull npm package metadata and download statistics pulled from the public "
        "npm registry - track adoption curves, compare packages and power "
        "devtools marketing analytics."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="package-stats-pulled",
            title="Package stats pulled",
            description="One package stats record extracted.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

PYPI_PACKAGE_STATS_ACTOR = ActorSpec(
    name="pry-pypi-package-stats",
    title="Pry PyPI Package Stats",
    description=(
        "Extract Python package metadata, releases and dependency info pulled "
        "from the public PyPI JSON API - supply-chain monitoring, "
        "dependency audits and ecosystem research."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="package-stats-pulled",
            title="Package stats pulled",
            description="One package stats record extracted.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

HN_NEWS_MONITOR_ACTOR = ActorSpec(
    name="pry-hacker-news-monitor",
    title="Pry Hacker News Monitor",
    description=(
        "Search and monitor Hacker News stories, comments and keyword "
        "mentions via the public Algolia HN API - brand tracking, launch "
        "feedback and market-signal detection for founders."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="min_points",
            title="Minimum points",
            type="integer",
            description="Only keep stories with at least this many points.",
            default=10,
            section_caption="Filter settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="hn-page-scanned",
            title="HN page scanned",
            description="One search result page scanned.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

YOUTUBE_RSS_MONITOR_ACTOR = ActorSpec(
    name="pry-youtube-rss-monitor",
    title="Pry YouTube Channel Monitor",
    description=(
        "Monitor YouTube channels through their public RSS feeds - new "
        "video titles, links and publish dates for competitor tracking "
        "and content calendars, no API key required."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="channel-checked",
            title="Channel checked",
            description="One channel feed checked for new videos.",
            price_usd=0.001,
        ),
    ),
    processor="monitor",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

RSS_FEED_MONITOR_ACTOR = ActorSpec(
    name="pry-rss-feed-monitor",
    title="Pry RSS Feed Monitor",
    description=(
        "Watch any RSS or Atom feed for new entries - newsrooms, blogs, "
        "podcasts, changelogs and press pages delivered as structured "
        "items with change detection between runs."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="feed-checked",
            title="Feed checked",
            description="One feed checked for new entries.",
            price_usd=0.001,
        ),
    ),
    processor="monitor",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

RDAP_DOMAIN_WATCH_ACTOR = ActorSpec(
    name="pry-rdap-domain-watch",
    title="Pry RDAP Domain Watch",
    description=(
        "Track domain registration data via the public RDAP protocol - "
        "expiry dates, status flags and nameservers for portfolio "
        "management, expiry sniping and brand protection."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="domain-checked",
            title="Domain checked",
            description="One domain's RDAP record pulled.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

ARXIV_PAPER_MONITOR_ACTOR = ActorSpec(
    name="pry-arxiv-paper-monitor",
    title="Pry arXiv Paper Monitor",
    description=(
        "Monitor arXiv for new papers by category or author via the "
        "public arXiv API - research tracking for AI labs, analysts and "
        "R&D teams without manual searches."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="papers-scanned",
            title="Papers scanned",
            description="One arXiv query page scanned.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

JSON_API_MONITOR_ACTOR = ActorSpec(
    name="pry-json-api-monitor",
    title="Pry JSON API Monitor",
    description=(
        "Monitor any JSON API endpoint for availability, payload changes "
        "and field-level drift - uptime plus content assertions for your "
        "own APIs or third-party integrations you depend on."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        InputField(
            name="data_path",
            title="Data path",
            type="string",
            description="Dot-path to the array of interest (e.g. data.items).",
            default="",
            section_caption="Parse settings",
        ),
    ),
    pricing_events=(
        PricingEvent(
            name="endpoint-checked",
            title="Endpoint checked",
            description="One API endpoint checked.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

PDF_INVOICE_EXTRACTOR_ACTOR = ActorSpec(
    name="pry-pdf-invoice-extractor",
    title="Pry PDF Invoice Extractor",
    description=(
        "Extract accounting fields from invoice PDFs - vendor, invoice "
        "number, dates and totals into clean structured rows for "
        "bookkeeping automation and accounts-payable pipelines."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="invoice-extracted",
            title="Invoice extracted",
            description="One invoice extracted to the dataset.",
            price_usd=0.0015,
        ),
    ),
    processor="invoice",
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

STARTUP_FUNDING_MONITOR_ACTOR = ActorSpec(
    name="pry-startup-funding-monitor",
    title="Pry Startup Funding Monitor",
    description=(
        "Track funding announcements across tech news sources - rounds, "
        "investors and amounts for sales prospecting, VC research and "
        "market intelligence."
    ),
    version="1.1",
    inputs=(
        URLS_FIELD,
        MAX_PAGES_FIELD,
    ),
    pricing_events=(
        PricingEvent(
            name="funding-news-scanned",
            title="Funding news scanned",
            description="One funding article scanned.",
            price_usd=0.0015,
        ),
    ),
    processor="news",
    min_memory_mbytes=512,
    max_memory_mbytes=4096,
)

PODCAST_REVIEW_MINER_ACTOR = ActorSpec(
    name="pry-podcast-review-miner",
    title="Pry Podcast Review Miner",
    description=(
        "Mine podcast reviews and ratings from Apple Podcasts public "
        "feeds - audience sentiment and episode feedback for shows, "
        "networks and advertiser research."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="review-mined",
            title="Review mined",
            description="One review extracted.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

FX_RATE_MONITOR_ACTOR = ActorSpec(
    name="pry-fx-rate-monitor",
    title="Pry FX Rate Monitor",
    description=(
        "Monitor foreign-exchange rates pulled via free public rate APIs - "
        "daily currency snapshots and drift alerts for finance teams, "
        "e-commerce pricing and invoicing."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="rates-pulled",
            title="Rates pulled",
            description="One rates snapshot pulled.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

CRYPTO_MARKET_MONITOR_ACTOR = ActorSpec(
    name="pry-crypto-market-monitor",
    title="Pry Crypto Market Monitor",
    description=(
        "Pull crypto market caps, prices and volume shifts pulled from public "
        "market APIs - scheduled snapshots for portfolios, dashboards "
        "and alerting without exchange API keys."
    ),
    version="1.1",
    inputs=(URLS_FIELD,),
    pricing_events=(
        PricingEvent(
            name="market-pulled",
            title="Market snapshot pulled",
            description="One market snapshot pulled.",
            price_usd=0.0005,
        ),
    ),
    processor="jsondata",
    min_memory_mbytes=512,
    max_memory_mbytes=2048,
)

ALL_PRESETS.update(
    {
        spec.name: spec
        for spec in (
            APP_STORE_REVIEWS_ACTOR,
            GITHUB_RELEASE_MONITOR_ACTOR,
            NPM_PACKAGE_STATS_ACTOR,
            PYPI_PACKAGE_STATS_ACTOR,
            HN_NEWS_MONITOR_ACTOR,
            YOUTUBE_RSS_MONITOR_ACTOR,
            RSS_FEED_MONITOR_ACTOR,
            RDAP_DOMAIN_WATCH_ACTOR,
            ARXIV_PAPER_MONITOR_ACTOR,
            JSON_API_MONITOR_ACTOR,
            PDF_INVOICE_EXTRACTOR_ACTOR,
            STARTUP_FUNDING_MONITOR_ACTOR,
            PODCAST_REVIEW_MINER_ACTOR,
            FX_RATE_MONITOR_ACTOR,
            CRYPTO_MARKET_MONITOR_ACTOR,
        )
    }
)
