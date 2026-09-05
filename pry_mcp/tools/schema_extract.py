"""Pry - MCP tool definitions: ScrapeGraphAI-style schema-based extraction.

Tools for extracting structured data from URLs using a JSON schema instead
of CSS selectors — the AI figures out where the data lives on the page.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_SCHEMA_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_extract_schema",
        "description": (
            "Extract structured data from a URL using a JSON schema — no CSS selectors needed. "
            'You describe WHAT you want (e.g. {"product_name": "the product title", '
            '"price": "current price in USD", "reviews": "customer reviews"}) and the engine '
            "figures out WHERE it lives on the page: JSON-LD structured data first, then meta tags, "
            "then AI extraction for anything left over. Works across any page structure. "
            "Example: pry_extract_schema(url='https://store.example.com/widget', "
            "schema={'name': 'product name', 'price': 'price', 'rating': 'average rating'}) "
            "→ {'url': ..., 'data': {'name': 'Widget', 'price': '$9.99', 'rating': '4.5'}, "
            "'method': 'pattern', 'confidence': 1.0}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to extract data from, e.g. https://example.com/product/123",
                },
                "schema": {
                    "type": "object",
                    "description": (
                        "JSON schema describing the data you want. Flat form: "
                        '{"field_name": "description of what to extract"}. Structured form also '
                        'accepted: {"fields": [{"name": "price", "description": "current price"}]}'
                    ),
                },
                "use_ai": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Fall back to AI (LLM) extraction for fields pattern extraction could not find "
                        "(default: true)"
                    ),
                },
            },
            "required": ["url", "schema"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "data": {
                    "type": "object",
                    "description": "Extracted fields matching the schema keys",
                },
                "method": {
                    "type": "string",
                    "enum": ["pattern", "ai", "hybrid", "none"],
                    "description": "Extraction strategy that produced the result",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Fraction of schema fields successfully extracted",
                },
            },
            "required": ["url", "data", "method", "confidence"],
        },
    },
    {
        "name": "pry_extract_batch",
        "description": (
            "Extract structured data from MULTIPLE URLs using the same JSON schema, with bounded "
            "concurrency (asyncio semaphore). Ideal for scraping a product catalog, a list of blog "
            "posts, or comparison pages. Example: pry_extract_batch("
            "urls=['https://store.example.com/a', 'https://store.example.com/b'], "
            "schema={'name': 'product name', 'price': 'price'}, max_concurrent=5) "
            "→ [{'url': ..., 'data': {'name': 'A', 'price': '$5'}, ...}, ...]. Results are returned "
            "in input order; each entry has the same shape as pry_extract_schema output."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string", "format": "uri"},
                    "description": "List of URLs to extract from, e.g. ['https://example.com/a', 'https://example.com/b']",
                },
                "schema": {
                    "type": "object",
                    "description": (
                        "JSON schema applied to every URL. Flat form: "
                        '{"field_name": "description"} or structured {"fields": [...]}'
                    ),
                },
                "max_concurrent": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Maximum parallel extractions (default: 5)",
                },
            },
            "required": ["urls", "schema"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "data": {"type": "object"},
                            "method": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                    },
                    "description": "One result per input URL, in input order",
                },
            },
            "required": ["results"],
        },
    },
    {
        "name": "pry_extract_prompt",
        "description": (
            "Extract data using a natural-language prompt instead of a schema — ScrapeGraphAI-style "
            "smart extraction. Describe what you want in plain English and the LLM finds it on the "
            "page. Example: pry_extract_prompt(url='https://blog.example.com/post', "
            "prompt='Extract the article title, author, publish date, and a 2-sentence summary') "
            "→ {'url': ..., 'data': {'title': ..., 'author': ..., 'date': ..., 'summary': ...}, "
            "'method': 'ai', 'confidence': 0.85}. Optionally pass a schema to constrain the output "
            "shape. Slower than pry_extract_schema (uses the LLM) but handles vague or open-ended "
            "requests."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to extract data from, e.g. https://example.com/article",
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "Natural-language description of what to extract, e.g. "
                        "'Extract the product name, price, and all reviews'"
                    ),
                },
                "schema": {
                    "type": "object",
                    "description": (
                        "Optional JSON schema to constrain the output shape, e.g. "
                        '{"title": "article title", "author": "author name"}'
                    ),
                },
            },
            "required": ["url", "prompt"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "data": {
                    "type": "object",
                    "description": "Extracted fields as described by the prompt",
                },
                "method": {
                    "type": "string",
                    "enum": ["ai", "none"],
                    "description": "Extraction method used",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
            },
            "required": ["url", "data", "method", "confidence"],
        },
    },
]
