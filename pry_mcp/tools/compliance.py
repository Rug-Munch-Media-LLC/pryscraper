"""Pry - MCP tool definitions: compliance / regulatory-watch tools and dispatcher..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from ._common import _call_domain_dispatcher, _new_domain_tool_kwargs

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_compliance",
        "description": (
            "Compliance intelligence in two modes: pass a URL to check whether scraping it "
            "is legally safe (robots.txt, ToS, GDPR/CCPA, PII exposure -> green/yellow/red "
            "risk score with recommendations), or pass query/agency to search regulatory "
            "compliance records — enforcement actions, fines, sanctions, and watchlist "
            "entries, e.g. query='Binance' for its regulatory history. "
            "Use before scraping an uncertain site or when screening a company for "
            "compliance exposure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": (
                        "The URL to run a legal compliance check on, e.g. https://example.com "
                        "(legacy URL-check mode — omit when using query/agency)"
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Regulatory compliance search query (company, entity, or topic), "
                        "e.g. 'Binance' or 'crypto exchange fines'"
                    ),
                },
                "agency": {
                    "type": "string",
                    "description": (
                        "Optional regulator / agency filter for the compliance search, "
                        "e.g. 'SEC', 'FTC', 'CFTC', 'OFAC'"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of compliance records to return (default: 20)",
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "risk_level": {
                            "type": "string",
                            "enum": ["green", "yellow", "red"],
                        },
                        "risk_score": {"type": "number"},
                        "checks": {"type": "array", "items": {"type": "object"}},
                        "recommendations": {"type": "array", "items": {"type": "string"}},
                        "query": {"type": "string"},
                        "agency": {"type": "string"},
                        "records": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {"type": "string"},
                                    "title": {"type": "string"},
                                    "agency": {"type": "string"},
                                    "date": {"type": "string"},
                                    "severity": {"type": "string"},
                                    "source": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    }
]

PRY_WATCH_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_company_watch",
        "description": (
            "Return the regulatory watch record for a company — recent enforcement "
            "actions, fines, sanctions, and compliance filings — e.g. company='OpenAI' "
            "for its compliance exposure. "
            "Use for due diligence, vendor screening, or competitor risk monitoring "
            "before partnering or trading. Backed by free public regulatory feeds; "
            "degrades to an empty record when no data is found."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name to watch, e.g. 'OpenAI'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of watch records to return (default: 20)",
                },
            },
            "required": ["company"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"},
                        "findings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {"type": "string"},
                                    "title": {"type": "string"},
                                    "date": {"type": "string"},
                                    "severity": {"type": "string"},
                                    "source": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    }
]

_COMPLIANCE_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_compliance": (
        (
            "enforcement",
            (
                "search_enforcement",
                "search_compliance",
                "compliance_search",
                "check_compliance",
                "get_compliance",
            ),
        ),
    ),
    "pry_company_watch": (
        ("enforcement", ("watch_company", "company_watch", "get_company_watch")),
    ),
}


async def call_compliance_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch compliance-data MCP tools to their ``compliance_data`` handlers (guarded).

    ``pry_compliance`` keeps a legacy URL-check mode: when called with only a
    ``url`` (no ``query``/``agency``) this dispatcher returns ``None`` so the
    original legal-risk REST proxy (``POST /v1/compliance/check``) keeps
    serving that mode while the ``compliance_data`` package lands. With
    ``query``/``agency`` it dispatches to the regulatory search. All imports
    are guarded so a missing module degrades to a readable message. Returns
    ``None`` for non-compliance tools so callers fall through.
    """
    if name == "pry_compliance" and not arguments.get("query") and not arguments.get("agency"):
        return None
    return await _call_domain_dispatcher(
        name,
        arguments,
        "compliance_data",
        _COMPLIANCE_TOOL_FNS,
        _new_domain_tool_kwargs,
        required_args={"pry_company_watch": "company"},
    )
