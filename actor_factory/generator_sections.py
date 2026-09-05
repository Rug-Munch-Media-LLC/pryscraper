"""— Apify Actor Factory: README section renderers.

Per-processor README sections: FAQ, tutorial steps, limitations,
troubleshooting and tips.

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

if TYPE_CHECKING:
    from actor_factory.spec import ActorSpec


def _render_faq(spec: ActorSpec) -> str:
    """Category-aware FAQ: context-appropriate platform answers (API-backed
    Actors don't get anti-bot questions - they don't scrape), processor
    Q&As, and per-option entries from the Actor's own input fields."""
    proc = spec.processor or ""
    faq: list[tuple[str, str]] = [
        (
            "Is this allowed?",
            "We stick to publicly available data and documented sources, "
            "and we respect robots.txt, ToS and privacy law. The core "
            "even ships compliance tooling - consent handling, deletion, "
            "retention - for self-hosters.",
        ),
    ]
    if proc != "jsondata":
        # Anti-bot escalation is irrelevant for public-API Actors; asking
        # (and answering) it there would read like boilerplate nobody wrote.
        faq.append(
            (
                "What happens when a site blocks the request?",
                "That's what the adaptive ladder is for. Blocked responses "
                "escalate automatically - headers first, stealth browsers "
                "later - until something gets through or every tier reports "
                "failure honestly.",
            )
        )
    if proc == "monitor":
        faq.append(
            (
                "How should I schedule this?",
                "Hourly or daily schedules are the sweet spot. First run "
                "captures a baseline; after that you only hear about actual "
                "changes. Apify scheduling handles the rest.",
            )
        )
    else:
        faq.append(
            (
                "Can I run this on a schedule?",
                "Absolutely - scheduling, API access and webhooks are "
                "first-class Apify features. Set it once and the dataset "
                "keeps itself fresh.",
            )
        )
    if proc == "extract":
        faq.extend(
            [
                (
                    "Which sites does this work on?",
                    "Any site embedding schema.org structured data (JSON-LD) - "
                    "that includes Shopify, WooCommerce, Magento and most modern "
                    "platforms. Pages without matching structured data are "
                    "skipped and reported honestly rather than guessed at.",
                ),
                (
                    "What happens with pages that have no structured data?",
                    "They appear in the dataset with status 'skipped' and a "
                    "clear reason - you always know exactly what was extracted "
                    "versus what was not found.",
                ),
            ]
        )
    if proc == "monitor":
        faq.extend(
            [
                (
                    "How does change detection work?",
                    "Each capture computes a stable content fingerprint; the "
                    "next run compares against it and reports changed/unchanged "
                    "with a similarity detail. The first run is always a baseline.",
                ),
                (
                    "Will I get an item every run even when nothing changed?",
                    "By default unchanged pages are suppressed so your dataset "
                    "only holds signal. Set include_unchanged to keep every "
                    "capture for audit trails.",
                ),
            ]
        )
    if proc == "audit":
        faq.extend(
            [
                (
                    "What does the audit score mean?",
                    "A 0-100 weighted summary: each failed check costs 25 "
                    "points, each warning 10. Individual findings always ship "
                    "alongside the score so nothing is hidden behind a number.",
                ),
                (
                    "Can I disable checks I don't need?",
                    "Yes - every check is toggleable via the input options, so "
                    "you pay only for the signals you care about.",
                ),
            ]
        )
    if proc == "tech":
        faq.append(
            (
                "How are technologies detected?",
                "Signature-based matching against HTML markers (script sources, "
                "meta tags, DOM attributes) across CMS, e-commerce, framework, "
                "analytics, payments and hosting categories - no visitor-side "
                "fingerprinting involved.",
            )
        )
    if proc == "leads":
        faq.append(
            (
                "Are the emails verified?",
                "Addresses are extracted and de-duplicated from page content "
                "and mailto links; deliverability verification is best done "
                "downstream with a dedicated verifier API.",
            )
        )
    if proc == "jsondata":
        faq.extend(
            [
                (
                    "How reliable is this data source?",
                    "This Actor reads a documented public API or feed - the same "
                    "data you would get querying it yourself, without scraping "
                    "fragility. No anti-bot lottery, no silent breakage.",
                ),
                (
                    "The response is not JSON - what happened?",
                    "Items arrive with status 'skipped' and the parse error in "
                    "the error field, so you can see exactly which URLs need "
                    "attention instead of guessing from empty results.",
                ),
            ]
        )
    if proc == "invoice":
        faq.append(
            (
                "Which invoice layouts are supported?",
                "Text-based invoices with standard fields (invoice number, "
                "dates, totals). Scanned image-only PDFs need OCR first; "
                "items without detectable fields are skipped and reported.",
            )
        )
    # Identity entry: every Actor answers what IT delivers, from its own
    # spec - guarantees per-Actor uniqueness and states the contract up front.
    faq.insert(
        0,
        (
            f"What exactly does {spec.title} deliver?",
            f"{spec.description} Results land in the dataset as structured "
            "items with transparent status reporting.",
        ),
    )
    # Per-option entries: every non-default input knob gets an honest Q&A
    # derived from its own description - unique per Actor by construction.
    for f in spec.inputs:
        if f.name in ("urls", "output_format") or not f.description:
            continue
        q = f"What does the **{f.title}** option do?"
        a = f"{f.description}"
        if f.default is not None and f.default != "":
            a += f" Default: `{f.default}`."
        faq.append((q, a))
    return "\n\n".join(f"**{q}** {a}" for q, a in faq) + "\n\n"


def _tutorial_steps(spec: ActorSpec) -> str:
    """Processor-aware getting-started steps - generic boilerplate here is
    the fastest way to look like nobody read their own README."""
    proc = spec.processor or ""
    if proc == "jsondata":
        return (
            "1. Paste the API endpoint(s) you want tracked into `urls` - the "
            "README's *Data source* section shows the exact URL pattern.\n"
            "2. Set `data_path` if the array you want lives deeper in the "
            "payload (e.g. `data.items`).\n"
            "3. Hit **Start** - JSON responses come back as clean dataset "
            "records; non-JSON replies are flagged, not buried.\n"
            "4. Schedule it or wire a webhook - exports work as "
            "JSON/CSV/Excel or straight via API.\n\n"
        )
    if proc == "monitor":
        return (
            "1. Add the page(s) or feed(s) to watch in `urls`.\n"
            "2. Run once - that first run captures the **baseline** fingerprint.\n"
            "3. Schedule runs (hourly/daily both work). Changed pages land in "
            "the dataset with a similarity detail; unchanged ones stay quiet.\n"
            "4. Want an audit trail instead? Flip on `include_unchanged` and "
            "every capture is kept.\n\n"
        )
    if proc == "audit":
        return (
            "1. Drop your target URLs into `urls`.\n"
            "2. Toggle only the checks you care about - each disabled check "
            "is compute you don't pay for.\n"
            "3. Click **Start** - findings arrive severity-ranked with a "
            "0-100 score per page.\n"
            "4. Sort by score in the dataset view; worst offenders float up.\n\n"
        )
    if proc == "extract":
        return (
            "1. Point `urls` at the pages carrying the structured data "
            "(product pages, recipe posts, FAQ centers...).\n"
            "2. Keep defaults or narrow the entity types to extract.\n"
            "3. Click **Start** - entities stream in as typed, flattened "
            "records; pages without matching data report as skipped.\n"
            "4. Export via dataset UI, API, or webhook.\n\n"
        )
    if proc == "invoice":
        return (
            "1. Add links to the invoice PDFs in `urls`.\n"
            "2. Click **Start** - the engine parses each document and pulls "
            "vendor hints, invoice numbers, dates and totals.\n"
            "3. Review the dataset; documents without detectable fields are "
            "listed with reasons rather than guessed values.\n"
            "4. Export to CSV/Excel for your bookkeeping flow.\n\n"
        )
    if proc == "tech":
        return (
            "1. Add the sites you want profiled to `urls`.\n"
            "2. Leave header inspection on unless you only want HTML signals.\n"
            "3. Click **Start** - technologies arrive categorized (CMS, "
            "e-commerce, analytics, payments...) with counts.\n"
            "4. Chain it: feed results into leads tooling for stack-based "
            "prospecting.\n\n"
        )
    return (
        "1. Add your target URLs to the `urls` field (one per entry).\n"
        "2. Adjust optional settings or keep the defaults - they're tuned "
        "for the common case.\n"
        "3. Click **Start** - results stream into the dataset as each URL "
        "finishes.\n"
        "4. Export as JSON/CSV/Excel, or consume via API/webhook.\n\n"
    )


def _limitations_section(spec: ActorSpec) -> str:
    proc = spec.processor or ""
    if proc == "jsondata":
        body = (
            "- Sources must return JSON (or JSON inside HTML) - binary or "
            "pure-HTML endpoints are reported as `skipped`, not guessed\n"
            "- Free/public API tiers apply their own rate limits; very large "
            "batches may need scheduling across runs\n"
            "- Authentication-protected endpoints need publicly reachable "
            "URLs - private dashboards are out of scope\n"
        )
    elif proc == "monitor":
        body = (
            "- The first run only establishes the baseline - differences "
            "appear from the second run onward\n"
            "- Heavily JavaScript-rendered pages may need the browser tier, "
            "which is slower than plain HTTP fetches\n"
            "- Cosmetic changes (ads, rotating banners) are filtered, but "
            "very noisy pages can still produce low-value diffs\n"
        )
    else:
        body = (
            "- Publicly accessible pages only - login-walled or paywalled "
            "content is not supported\n"
            "- Extremely aggressive anti-bot targets may still block some "
            "requests; failures are reported honestly per URL\n"
            "- Data quality mirrors the source: if a page hides its data "
            "behind images or canvas, extraction may be partial\n"
        )
    return "## Limitations\n\n" + body + "\n"


def _troubleshooting_section(spec: ActorSpec) -> str:
    return (
        "## Troubleshooting\n\n"
        "- **Empty dataset?** Check the run log - each URL is reported with "
        "`ok`, `skipped` or `error` and a reason; fix the flagged targets "
        "and re-run\n"
        "- **Blocked or 403 responses?** The adaptive ladder escalates "
        "automatically; if a target still fails, lower `max_items` and "
        "retry later, or schedule runs further apart\n"
        "- **Unexpected fields?** Compare your output against the example "
        "below - `data_path` (where present) controls which array is "
        "extracted\n"
        "- **Run stopped early?** You hit the spending limit or `max_items` "
        "cap - raise the cap and resume; completed items are always "
        "flushed to the dataset\n\n"
    )


def _tips_section(spec: ActorSpec) -> str:
    """1-2 practical usage tips, tuned per processor."""
    proc = spec.processor or ""
    if proc == "monitor":
        tips = (
            "- **Baseline first**: run once manually before scheduling - the "
            "first run only records the fingerprint, so scheduled diffs are "
            "meaningful from run two onward\n"
            "- **Filter in the dataset**: enable `include_unchanged` only for "
            "audit trails; for alerting, keep it off and let webhooks fire "
            "on the changed items alone\n"
        )
    elif proc == "jsondata":
        tips = (
            "- **Use `data_path`** to point at the exact array you want "
            "(e.g. `data.items`) - you get one clean record per element "
            "instead of one blob per response\n"
            "- **Batch smart**: group endpoints that share rate limits into "
            "separate scheduled runs rather than one huge batch\n"
        )
    else:
        tips = (
            "- **Start small, then scale**: validate output on 2-3 URLs "
            "first, then raise `max_items` and schedule bulk runs - failed "
            "targets are reported per-URL, so retries are cheap\n"
            "- **Automate the boring part**: pair an Apify schedule with a "
            "webhook and the dataset lands in your pipeline without any "
            "manual runs\n"
        )
    return "## Tips\n\n" + tips + "\n"
