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
            title="Viewport width",
            type="integer",
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
