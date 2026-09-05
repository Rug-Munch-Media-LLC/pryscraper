"""— Apify Actor Factory: example dataset items and URL helpers.

Processor-specific realistic dataset samples for README output references,
plus example-URL resolution for docs/curl snippets.

Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from actor_factory.spec import ActorSpec


def _default_output_format(spec: ActorSpec) -> str:
    for f in spec.inputs:
        if f.name == "output_format" and isinstance(f.default, str):
            return f.default
    return "markdown"


def _example_url(spec: ActorSpec) -> str:
    """Real example URL for docs/curl snippets: the actor's own prefill
    target when it has one, otherwise a stable generic page. Never
    example.com - buyers read placeholder URLs as unfinished work."""
    for f in spec.inputs:
        if f.name == "urls" and isinstance(f.prefill, list):
            for entry in f.prefill:
                if isinstance(entry, dict) and entry.get("url"):
                    return str(entry["url"])
    return "https://news.ycombinator.com"


def _example_item(spec: ActorSpec) -> str:
    """Processor-specific realistic dataset sample for the README.

    Every Actor's Output reference must show what THIS Actor actually
    emits - identical generic samples across a catalog read as automated
    boilerplate and hide the real contract from buyers.
    """
    ts = "2026-01-01T00:00:00+00:00"
    src = _example_url(spec)
    base = {"url": src, "status": "ok", "method": "direct", "scraped_at": ts}
    proc = spec.processor or ""
    name = spec.name.lower()

    if proc == "extract":
        if "recipe" in name:
            entity = {
                "type": "Recipe",
                "fields": {
                    "name": "Best Hummus",
                    "recipeYield": "4 servings",
                    "totalTime": "PT15M",
                    "recipeIngredient[0]": "1 can chickpeas",
                },
            }
        elif "knowledge-base" in name or "faq" in name:
            entity = {
                "type": "FAQPage",
                "fields": {
                    "mainEntity[0].name": "How do I reset my password?",
                    "mainEntity[0].acceptedAnswer.text": "Open Settings and choose Reset...",
                },
            }
        elif "local-business" in name:
            entity = {
                "type": "LocalBusiness",
                "fields": {
                    "name": "Corner Bakery",
                    "telephone": "+1-555-0100",
                    "address.streetAddress": "12 Main St",
                    "geo.latitude": 40.7128,
                },
            }
        else:  # Product (e-commerce family)
            entity = {
                "type": "Product",
                "fields": {
                    "name": "Wool Runner",
                    "brand": "Example",
                    "offers.price": "98.00",
                    "offers.priceCurrency": "USD",
                    "offers.availability": "InStock",
                },
            }
        item = {**base, "extracted": {"entities": [entity]}}
    elif proc == "monitor":
        item = {
            **base,
            "monitor": {
                "fingerprint": "1100011010110100",
                "changed": True,
                "detail": "simhash distance 9 (threshold 3)",
            },
        }
    elif proc == "audit":
        item = {
            **base,
            "audit": {
                "score": 75,
                "failed": 1,
                "warnings": 0,
                "findings": [
                    {
                        "check": "images_alt_text",
                        "status": "warn",
                        "detail": "2/6 images missing alt text",
                    },
                    {
                        "check": "privacy_policy_link",
                        "status": "fail",
                        "detail": "no /privacy link on page",
                    },
                ],
            },
        }
    elif proc == "jsondata":
        if "github" in name:
            rec = {
                "tag_name": "v2.1.0",
                "name": "Release v2.1.0",
                "published_at": "2026-01-01T00:00:00Z",
                "prerelease": False,
            }
        elif "npm" in name or "pypi" in name:
            rec = {
                "name": "example-package",
                "version": "1.4.2",
                "description": "Example package.",
                "downloads.last-month": "48,112",
            }
        elif "rdap" in name or "domain" in name:
            rec = {
                "ldhName": "EXAMPLE.COM",
                "status[0]": "active",
                "events[0].eventAction": "expiration",
                "events[0].eventDate": "2027-01-01T00:00:00Z",
            }
        elif "app-store" in name or "podcast" in name:
            rec = {
                "id": "1234567",
                "title": "Exactly what I needed",
                "content": "Saved me hours every week.",
                "rating": 5,
            }
        elif "fx" in name:
            rec = {
                "base_code": "USD",
                "rates.EUR": 0.92,
                "rates.GBP": 0.79,
                "time_last_update_utc": "Mon, 01 Jan 2026 00:00:00 +0000",
            }
        elif "crypto-market" in name:
            rec = {
                "id": "bitcoin",
                "current_price": 96000.0,
                "market_cap": 1900000000000,
                "total_volume": 42000000000,
            }
        elif "arxiv" in name:
            rec = {
                "title": "An Example Paper",
                "published": "2026-01-01",
                "summary": "We demonstrate...",
                "id": "http://arxiv.org/abs/2601.00001v1",
            }
        else:  # generic API monitor / HN
            rec = {
                "objectID": "41000001",
                "title": "Show HN: example",
                "points": 128,
                "num_comments": 44,
            }
        item = {**base, "data": {"records": [rec], "count": 1, "total_in_response": 25}}
    elif proc == "invoice":
        item = {
            **base,
            "invoice": {
                "number": "INV-2026-0042",
                "date": "2026-01-01",
                "total": "109.00",
                "currency": "$",
                "vendor_hint": "ACME Corp",
            },
        }
    elif proc == "tech":
        item = {
            **base,
            "tech": {
                "technologies": [
                    {"category": "generator_meta", "name": "WordPress 6.4"},
                    {"category": "ecommerce", "name": "Shopify"},
                    {"category": "payments", "name": "Stripe"},
                ],
                "count": 3,
                "categories": ["ecommerce", "generator_meta", "payments"],
            },
        }
    elif proc == "leads":
        item = {
            **base,
            "leads": {
                "emails": ["hello@example.com", "support@example.com"],
                "phones": ["+1 555 010 1000"],
                "social_links": ["https://linkedin.com/company/example"],
                "contact_form_present": True,
            },
        }
    elif proc == "seo":
        item = {
            **base,
            "seo": {
                "title": "Example - Home",
                "meta_description": "Example site description.",
                "canonical": "https://example.com/",
                "issues": ["missing_og_image"],
                "images_total": 6,
                "images_missing_alt": 2,
            },
        }
    elif proc == "news":
        item = {
            **base,
            "news": {
                "headline": "Example raises Series B",
                "published": ts,
                "summary": "Example Corp announced...",
                "links": ["https://example.com/post"],
            },
        }
    elif proc == "price":
        item = {
            **base,
            "price": {
                "amount": 98.00,
                "currency": "USD",
                "availability": "InStock",
                "source": "jsonld",
            },
        }
    else:  # raw capture (universal/crawler/screenshot/document-parser/...)
        item = {
            **base,
            "content": "# Example page\n\nClean markdown content...",
            "metadata": {
                "domain": src.removeprefix("https://").removeprefix("http://").split("/")[0],
                "content_length": 1234,
            },
        }

    return json.dumps(item, indent=2)
