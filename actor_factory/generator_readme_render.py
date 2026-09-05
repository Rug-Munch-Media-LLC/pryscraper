"""— Apify Actor Factory: README assembly.

Composes the full store-winning README.md from section renderers.

Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING

from actor_factory.economics import WorkloadProfile, run_economics
from actor_factory.generator_copy import _topic, _use_case_bullets
from actor_factory.generator_data_sources import _data_source_section
from actor_factory.generator_examples import _example_item, _example_url
from actor_factory.generator_sections import (
    _limitations_section,
    _render_faq,
    _tips_section,
    _troubleshooting_section,
    _tutorial_steps,
)

if TYPE_CHECKING:
    from actor_factory.spec import ActorSpec


def _render_readme(spec: ActorSpec) -> str:
    """Store-winning README per Apify's actor-readme best practices.

    Docs requirements encoded here:
    - >=300 words; H2/H3 only (H1 is the actor name on Store)
    - Introduction with bold keyword highlights
    - Step-by-step tutorial (ordered list reassures users, SEO-friendly)
     - Cost-expectation section with search-optimized H2 ("Pricing" /
       "How much will...")
     - Use Cases section (3 domain-relevant bullets)
     - Input/output reference incl. JSON example + dataset field glossary
     - Limitations + Troubleshooting sections
     - FAQ + support section
    - Platform advantages woven in (scheduling, API, proxies, monitoring)
    """
    primary = spec.primary_event()
    # Per-actor unique positioning: no two store pages share copy.
    _use_cases = {
        "monitor": "ops teams watching for outages, price changes and competitor moves",
        "news": "analysts tracking breaking coverage across sources",
        "jsondata": "data teams feeding structured records into warehouses and dashboards",
        "extract": "engineers converting pages into typed JSON contracts",
        "leads": "growth teams building verified prospect lists",
        "price": "pricing analysts tracking market movement hourly",
        "audit": "agencies running site audits at scale",
        "seo": "SEO consultants benchmarking visibility",
        "tech": "SaaS sellers detecting prospect tech stacks",
        "invoice": "finance automation pipelines parsing documents",
        "corpus": "AI teams assembling clean training corpora",
        "backlinks": "SEO agencies auditing link profiles",
        None: "developers who need any page as clean markdown on demand",
    }
    _audience = _use_cases.get(spec.processor, "teams that need this data reliably")
    _inp = ", ".join(f.name for f in spec.inputs[:3])
    _unique_intro = (
        f"{spec.title.removeprefix('Pry ')} — {spec.description} "
        f"Built for {_audience}. Configure your targets via {(_inp or 'the URL input')}, "
        f"run on a schedule or on demand, and collect results as clean structured "
        f"data. Automatic retries, proxy orchestration and resilient extraction "
        f"are handled for you."
    )

    events_table = "\n".join(
        f"| `{e.name}` | {e.title} | ${e.price_usd:.4f} | {e.description} |"
        for e in spec.pricing_events
    )
    fields_table = "\n".join(
        f"| `{f.name}` | {f.type} | {'yes' if f.required else 'no'} | {f.description or f.title} |"
        for f in spec.inputs
    )
    example_item = _example_item(spec)
    example_url = _example_url(spec)
    example_cost = run_economics(
        price_per_item_usd=primary.price_usd,
        profile=WorkloadProfile(
            items_per_run=100,
            seconds_per_item=6.0,
            memory_mbytes=spec.min_memory_mbytes,
        ),
    )

    return (
        f"# {spec.title}\n\n"
        f"{spec.description}\n\n"
        f"> Need **{_topic(spec)} data** without infrastructure headaches? "
        "This actor scrapes, monitors and exports it on Apify's managed "
        "runtime - pay per result, no subscription.\n\n"
        f"This actor runs on the "
        "engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) "
        "with per-domain memory, block-signal detection and circuit breakers. "
        "Cheaper tiers are tried first; escalation happens only when a target "
        "actually fights back.\n\n"
        "## What it does\n\n"
        f"{spec.title.removeprefix('Pry ')} delivers fresh {_topic(spec)} "
        "as clean, structured data you can actually use - no infrastructure "
        "to run, no proxies to manage, no parsers to maintain. Point it at "
        "your targets, and every result lands in the dataset with a per-URL "
        "status so downstream jobs can trust what they consume. You pay "
        "only for successfully processed items.\n\n"
        "## What can this Actor do?\n\n"
        f"- Process **{len(spec.inputs)} configured input groups** - URLs in, "
        "structured results out\n"
        "- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, "
        "Playwright, Googlebot emulation, Tor, premium proxies, archives\n"
        "- **Transparent billing**: pay-per-event, charged per processed item\n"
        "- **Platform perks**: scheduling, API access, proxy rotation, "
        "monitoring and webhooks come free with Apify\n\n"
        "## Use Cases\n\n"
        + _use_case_bullets(spec)
        + "## Tutorial\n\n"
        + _tutorial_steps(spec)
        + "## Pricing\n\n"
        "### How much will it cost to scrape with this Actor?\n\n"
        f"Billing is **pay-per-event**: you are charged `${primary.price_usd:.4f}` "
        f"per `{primary.name}` ({primary.description.lower()}) - that is "
        f"**${primary.price_usd * 1000:.2f} per 1,000 items**, with no "
        "subscription and no minimum.\n\n"
        f"Example: 100 items at {spec.min_memory_mbytes} MB costs roughly "
        f"**${example_cost['revenue_usd']:.2f}** in event charges "
        f"(platform compute adds about ${example_cost['platform_cost_usd']:.4f}). "
        "The synthetic `apify-actor-start` event covers startup compute. Your "
        "spending limit is always respected - the run stops gracefully at the cap.\n\n"
        "### Events\n\n"
        "| Event | Title | Price | Description |\n|---|---|---|---|\n"
        f"{events_table}\n\n"
        "## Input reference\n\n"
        "| Field | Type | Required | Description |\n|---|---|---|---|\n"
        f"{fields_table}\n\n"
        "## Output reference\n\n"
        "Each dataset item looks like this:\n\n"
        f"```json\n{example_item}\n```\n\n"
        "### Dataset fields\n\n"
        "- `url` - the source URL that produced this item\n"
        "- `status` - `ok`, `skipped` or `error`, so downstream jobs can "
        "filter reliably\n"
        "- `method` - which tier of the fallback chain succeeded "
        "(transparency into how the data was fetched)\n"
        "- `scraped_at` - ISO-8601 UTC timestamp for time-series use\n"
        "- `data` / `content` - the extracted payload (structured records "
        "or clean markdown, depending on the actor)\n\n"
        'Items with `status: "error"` include an `error` reason - invalid '
        "targets are billed transparently and never silently dropped.\n\n"
        + _data_source_section(spec)
        + "## How can I use this data?\n\n"
        f"- **Market research** - track {primary.name.replace('-', ' ')} "
        "trends across competitors\n"
        "- **Alerting** - pair with Apify schedules + webhooks for "
        "real-time notifications\n"
        "- **AI pipelines** - dataset exports feed directly into "
        "LLM/RAG workflows\n"
        "- **Reporting** - export to JSON/CSV/Excel or consume via the "
        "Apify API in your own tools\n\n"
        "## More actors\n\n"
        "This actor is part of the "
        "[actor family](https://apify.com/cryptorugmuncher) - 50+ "
        "scrapers, crawlers and monitors covering SERP, maps leads, LLM "
        "corpora, compliance monitoring and dark-web sources. Same engine, "
        "same reliability, one subscription-free billing model.\n\n"
        "## Using this Actor with the Apify API\n\n"
        "Run it programmatically:\n\n"
        "```bash\n"
        "curl -X POST https://api.apify.com/v2/acts/~run \\\\\n"
        '  -H "Authorization: Bearer $APIFY_TOKEN" \\\\\n'
        '  -H "Content-Type: application/json" \\\\\n'
        f'  -d \'{{"urls": ["{example_url}"]}}\'\n'
        "```\n\n"
        "Integrations: Zapier, Make, n8n, Airbyte and webhooks are "
        "first-class on the Apify platform.\n\n"
        + _limitations_section(spec)
        + _troubleshooting_section(spec)
        + _tips_section(spec)
        + "## FAQ\n\n"
        + _render_faq(spec)
        + "## Support\n\n"
        "Issues and feature requests: "
        "[repository](https://codeberg.org/RugMunchMedia/pryscraper). "
        "Questions or custom-actor requests: [support@pryscraper.com]"
        "(mailto:support@pryscraper.com).\n"
    )
