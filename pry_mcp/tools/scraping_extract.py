"""Pry - MCP tool definitions: enrichment / document parsing / screenshot tools.

Split from the former ``pry_mcp/tools/scraping.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_EXTRACT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_enrich",
        "description": (
            "Enrich a URL with company info, tech stack detection, social profiles, and "
            "competitive intelligence. "
            "Use to build a prospect profile from their website before outreach, e.g. discover "
            "what stack a startup runs and find their LinkedIn."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to enrich, e.g. https://startup.example.com",
                }
            },
            "required": ["url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "company": {"type": "object"},
                        "tech_stack": {"type": "array", "items": {"type": "string"}},
                        "social_profiles": {"type": "object"},
                        "emails": {"type": "array", "items": {"type": "string"}},
                        "intelligence": {"type": "object"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_parse_document",
        "description": (
            "Parse a document (PDF, DOCX, image) and extract its text and tables using "
            "pdfplumber, Tesseract OCR, and python-docx. "
            "Use to pull content from a PDF spec, a scanned brochure, or a Word file, e.g. "
            "extract the pricing table from a vendor's PDF."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "Direct URL to the document, e.g. https://example.com/spec.pdf",
                }
            },
            "required": ["url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "content_type": {"type": "string"},
                        "text": {"type": "string"},
                        "tables": {"type": "array", "items": {"type": "object"}},
                        "pages": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_screenshot",
        "description": (
            "Render a URL in a headless browser and return a screenshot as a "
            "base64-encoded PNG with width, height, and content type. "
            "Use for visual verification or design QA of a rendered page — e.g. "
            "screenshot https://example.com/checkout with full_page=true to capture "
            "the whole checkout flow before launch. JavaScript is executed before "
            "capture so SPAs render correctly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to screenshot, e.g. https://example.com/checkout",
                },
                "full_page": {
                    "type": "boolean",
                    "default": True,
                    "description": "Capture the entire page height instead of just the viewport",
                },
            },
            "required": ["url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "image_base64": {"type": "string"},
                        "content_type": {"type": "string"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]
