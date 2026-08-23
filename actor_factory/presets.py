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
