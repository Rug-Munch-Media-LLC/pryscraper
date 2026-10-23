"""Pry - prompt message bodies.

Builds the user message for each named prompt. The prompt DEFINITIONS
(name, description, arguments) live in ``pry_mcp.resources_prompts``; this
module only turns arguments into message text.

Note: ``pry_mcp.resources_prompts`` is a different module from this one.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def _user_message(text: str) -> dict[str, Any]:
    """One MCP user message carrying ``text``."""
    return {"role": "user", "content": {"type": "text", "text": text}}


def _prefix(label: str, value: str) -> str:
    """``'label value. '`` when ``value`` is set, else ``''``."""
    return f"{label}{value}. " if value else ""


def _research_company(arguments: dict[str, Any]) -> str:
    return (
        f"Research {arguments.get('company_name', 'the company')}. "
        f"{_prefix('Start by scraping ', arguments.get('website', ''))}"
        "Use pry_scrape and pry_enrich to gather data, then summarize: "
        "what they do, target market, key products, competitive positioning, "
        "and any risks or opportunities."
    )


def _compare_products(arguments: dict[str, Any]) -> str:
    query = arguments.get("product_query", "the product")
    sites = ", ".join(arguments.get("sites", []))
    return (
        f"Compare prices and details for '{query}' across {sites}. "
        "Use pry_template with amazon-product, walmart-product, etc. "
        "Return a side-by-side comparison table."
    )


def _extract_contacts(arguments: dict[str, Any]) -> str:
    return (
        f"Extract all contact information from {arguments.get('url', '')}. "
        f"Crawl up to {arguments.get('max_pages', 20)} pages. "
        "Use pry_crawl and regex to find emails, phones, and social profiles."
    )


def _monitor_competitor(arguments: dict[str, Any]) -> str:
    return (
        f"Set up monitoring for {arguments.get('url', '')}. "
        f"Track {arguments.get('what_to_track', 'changes')}. "
        f"{_prefix('Notify via webhook: ', arguments.get('webhook_url', ''))}"
        "Use pry_monitor."
    )


def _analyze_article(arguments: dict[str, Any]) -> str:
    return (
        f"Scrape and analyze this article: {arguments.get('url', '')}. "
        f"{_prefix('Focus on: ', arguments.get('focus', ''))}"
        "Summarize key points, sentiment, entities, and claims."
    )


def _extract_table(arguments: dict[str, Any]) -> str:
    return (
        f"Extract the data table from {arguments.get('url', '')}. "
        f"Table: {arguments.get('table_description', '')}. "
        "Use pry_extract with CSS selectors or pry_scrape + structured output."
    )


def _scrape_with_schema(arguments: dict[str, Any]) -> str:
    return (
        f"Scrape {arguments.get('url', '')} and extract these fields: "
        f"{arguments.get('fields', '')}. "
        "Use pry_extract with a custom JSON schema."
    )


_BUILDERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "research_company": _research_company,
    "compare_products": _compare_products,
    "extract_contacts": _extract_contacts,
    "monitor_competitor": _monitor_competitor,
    "analyze_article": _analyze_article,
    "extract_table": _extract_table,
    "scrape_with_schema": _scrape_with_schema,
}


def prompt_messages(name: str, arguments: dict[str, Any], title: str) -> list[dict[str, Any]]:
    """Message list for prompt ``name``; unknown prompts use the generic form."""
    builder = _BUILDERS.get(name)
    if builder is not None:
        return [_user_message(builder(arguments))]
    arg_text = ", ".join(f"{k}={v}" for k, v in arguments.items())
    return [_user_message(f"Execute the {title} prompt with arguments: {arg_text}")]
