"""Pry - MCP tool definitions: research / domain-intel tools and dispatcher..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from ._common import _call_domain_dispatcher
from ._kwargs_climate_research import _domain_tool_kwargs

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_papers",
        "description": (
            "Search academic papers and preprints (arXiv, Semantic Scholar, "
            "PubMed) by keyword, author, or topic and return titles, abstracts, "
            "and citation counts. "
            "Use for research pipelines that need scholarly grounding, e.g. "
            "'find recent papers on retrieval-augmented generation' or call with "
            "author='Smith' and limit=10 for recent works."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'retrieval augmented generation'",
                },
                "author": {
                    "type": "string",
                    "description": "Filter by author name, e.g. 'Smith'",
                },
                "year_from": {
                    "type": "integer",
                    "description": "Earliest publication year, e.g. 2020",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of papers (default: 20)",
                },
            },
            "required": ["query"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "authors": {"type": "array", "items": {"type": "string"}},
                            "abstract": {"type": "string"},
                            "year": {"type": "integer"},
                            "citations": {"type": "integer"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_domain",
        "description": (
            "Get a domain intelligence report: WHOIS registration, SSL/TLS "
            "details, hosting provider, and technology fingerprint for a "
            "website. "
            "Use to enrich leads, vet domains before scraping, or map a "
            "competitor's stack, e.g. 'what can you tell me about example.com?' "
            "or call with domain='rugmunch.io' for hosting and tech details."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Domain to analyze, e.g. 'example.com'",
                },
                "include_tech": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include technology fingerprint (default: true)",
                },
            },
            "required": ["domain"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string"},
                        "registrar": {"type": "string"},
                        "registered_at": {"type": "string"},
                        "expires_at": {"type": "string"},
                        "hosting_provider": {"type": "string"},
                        "tech_stack": {"type": "array", "items": {"type": "string"}},
                        "ssl_issuer": {"type": "string"},
                    },
                },
                "domain": {"type": "string"},
            },
            "required": ["success"],
        },
    },
]

_RESEARCH_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_papers": (
        ("academic", ("search_papers", "get_papers", "find_papers", "papers")),
        ("papers", ("search_papers", "get_papers", "find_papers", "papers")),
    ),
    "pry_domain": (
        ("domain", ("whois_lookup", "get_domain_report", "domain_report", "get_domain")),
        ("whois", ("whois_lookup", "get_domain_report", "domain_report", "get_domain")),
    ),
}


async def call_research_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch research MCP tools to their ``research_data`` handlers (guarded).

    The ``research_data`` subpackage (papers, domain) is built in parallel by
    other agents; every import is guarded so this dispatcher degrades
    gracefully (a readable message) if a module has not landed yet. Returns
    ``None`` for non-research tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name, arguments, "research_data", _RESEARCH_TOOL_FNS, _domain_tool_kwargs
    )
