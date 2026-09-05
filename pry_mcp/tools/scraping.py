"""Pry - MCP tool definitions: core scraping / extraction / parsing / source-registry tools.

Thin re-export facade over the focused modules:
``scraping_core`` (scrape/crawl/extract/templates), ``scraping_extract``
(enrich/parse/screenshot), ``scraping_sources`` (source registry).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from extraction.css import _validate_css_selector

from .scraping_core import PRY_TOOLS
from .scraping_extract import PRY_EXTRACT_TOOLS
from .scraping_sources import PRY_SOURCE_TOOLS

__all__ = [
    "PRY_EXTRACT_TOOLS",
    "PRY_SOURCE_TOOLS",
    "PRY_TOOLS",
    "validate_schema_selectors",
]


def validate_schema_selectors(schema: dict[str, Any]) -> dict[str, Any]:
    """Validate every user-supplied CSS selector in an extraction schema.

    ReDoS guard: ``pry_extract`` / ``pry_scrape`` accept a JSON schema whose
    ``base_selector`` and per-field ``selector`` values are passed straight to
    the cssselect engine. This validates them all up front (raising
    ``ValueError`` on the first unsafe selector) so a crafted schema cannot
    reach the extraction engine. Returns the schema unchanged when safe.
    """
    base_selector = schema.get("base_selector")
    if base_selector:
        _validate_css_selector(base_selector)
    for field in schema.get("fields", []):
        if not isinstance(field, dict):
            continue
        field_selector = field.get("selector", "")
        if field_selector:
            _validate_css_selector(field_selector)
    return schema
