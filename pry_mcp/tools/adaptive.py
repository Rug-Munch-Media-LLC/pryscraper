"""Pry - MCP tool definitions: adaptive selector scraping tools.

Scrapling-style adaptive extraction: selectors that auto-relocate when
a page's structure changes, using captured context (text, tag, attrs,
structural position).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_ADAPTIVE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_adaptive_scrape",
        "description": (
            "Scrape a page with adaptive selectors that auto-relocate when pages change "
            "(Scrapling-style). Provide a mapping of field names to CSS selectors; each "
            "selector is matched against the page, and if a selector breaks because the "
            "site was redesigned, the engine uses previously captured context (text "
            "content, tag name, attributes, parent/sibling structure) to find the element "
            "again and report a confidence score (1.0 = exact CSS match, 0.5 = relocated "
            "by context, 0.0 = not found). Pass old_html (a previously fetched version of "
            "the same page) to enable relocation against the new markup. Use when you "
            "scrape the same site repeatedly and want extraction to survive layout "
            "changes without manually updating selectors, e.g. "
            "adaptive_scrape(url='https://shop.example.com', selectors={'price': 'span.price', 'title': 'h1.product-name'}) "
            "returns the price and title even if the site changed its CSS classes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to scrape, e.g. https://example.com/prices",
                },
                "selectors": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": (
                        "Mapping of field names to CSS selectors, e.g. "
                        '{"price": ".price-value", "title": "h1.product-title"}'
                    ),
                },
                "old_html": {
                    "type": "string",
                    "description": (
                        "Optional previously fetched HTML of the same page. When provided, "
                        "selectors that no longer match are relocated in the new HTML "
                        "using context captured from the old HTML."
                    ),
                },
            },
            "required": ["url", "selectors"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "fields": {
                            "type": "object",
                            "additionalProperties": {"type": ["string", "null"]},
                            "description": "Extracted field values keyed by field name",
                        },
                        "confidence": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                            "description": (
                                "Per-field match confidence: 1.0 exact CSS match, "
                                "0.5 relocated by context, 0.0 not found"
                            ),
                        },
                        "relocated": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Field names whose selectors were relocated",
                        },
                        "missing": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Field names that could not be found",
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
]
