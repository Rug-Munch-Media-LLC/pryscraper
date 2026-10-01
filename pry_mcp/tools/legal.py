"""Pry - MCP tool definitions: legal / public-records tools and dispatcher..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
from typing import Any

from ._common import (
    _apply_offset,
    _data_module_unavailable,
    _missing_arg,
    _ModuleNotFound,
    resolve_domain_module,
)

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_legal_dockets",
        "description": (
            "Search U.S. federal and state court dockets by full-text query using the free "
            "CourtListener REST API v4, returning docket titles, courts, and case numbers. "
            "Use to monitor litigation against a company, person, or trademark before it "
            "hits the news, e.g. 'what lawsuits involve OpenAI?' or 'show dockets mentioning "
            "this company name'. Results are best-effort: the free tier has no auth and "
            "degrades to an empty list on network or rate-limit failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Full-text docket search query, e.g. 'OpenAI copyright infringement'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of dockets to return (default: 20)",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of dockets to skip before the page (pagination)",
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
                            "id": {"type": "integer"},
                            "case_name": {"type": "string"},
                            "court": {"type": "string"},
                            "docket_number": {"type": "string"},
                            "date_filed": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_legal_sec",
        "description": (
            "Search SEC EDGAR filings for a public company by ticker and form type, returning "
            "filing dates, form names, and EDGAR accession numbers. Use to track regulatory "
            "filings that move markets, e.g. 'recent 8-K filings for AAPL' or 'all 10-Q "
            "filings for TSLA this year'. Backed by the free EDGAR Full-Text Search and "
            "submissions feed; never raises and returns an empty list on failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Company ticker symbol, e.g. 'AAPL'",
                },
                "form_type": {
                    "type": "string",
                    "default": "8-K",
                    "description": "SEC form type to search (e.g. '8-K', '10-Q', '10-K', '4')",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of filings to return (default: 20)",
                },
            },
            "required": ["ticker"],
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
                            "accession_no": {"type": "string"},
                            "form_type": {"type": "string"},
                            "filing_date": {"type": "string"},
                            "ticker": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "ticker": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_legal_sanctions",
        "description": (
            "Screen a person or entity name against the OFAC Specially Designated Nationals "
            "(SDN) sanctions list, returning any matching records with their sanctions "
            "program and remarks. Use for compliance due diligence before onboarding a "
            "counterparty, partner, or wallet-linked entity, e.g. 'is Vladimir Potanin "
            "sanctioned?'. Backed by the free OFAC SDN XML downloads, cached in-process; "
            "returns an empty list when the name is clean or the feed is unreachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Person or entity name to screen, e.g. 'Vladimir Potanin'",
                }
            },
            "required": ["name"],
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
                            "name": {"type": "string"},
                            "program": {"type": "string"},
                            "remarks": {"type": "string"},
                            "uid": {"type": "string"},
                        },
                    },
                },
                "name": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
]


async def call_legal_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch legal/public-records MCP tools to their ``legal_docs`` handlers.

    The ``legal_docs`` subpackage (``dockets``, ``sec_filings``, ``sanctions``)
    is built in parallel by other agents; every import is guarded so this
    dispatcher degrades gracefully (a readable message) if a module has not
    landed yet. Returns ``None`` for non-legal tools so callers fall through.
    """
    if name == "pry_legal_dockets":
        query = arguments.get("query", "")
        if not query:
            return _missing_arg(name, "query")
        limit = int(arguments.get("limit", 20))
        try:
            dockets = resolve_domain_module("legal_docs", "dockets")
        except _ModuleNotFound:
            return _data_module_unavailable(name, "legal_docs")
        try:
            offset = int(arguments.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        # Over-fetch by offset so the slice still yields a full page.
        data = await dockets.search_dockets(query=query, limit=limit + offset)
        data, total = _apply_offset(data, arguments)
        payload: dict[str, Any] = {"success": True, "data": data, "query": query}
        if total:
            payload["total"] = total
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_legal_sec":
        ticker = arguments.get("ticker", "")
        if not ticker:
            return _missing_arg(name, "ticker")
        form_type = arguments.get("form_type", "8-K")
        limit = int(arguments.get("limit", 20))
        try:
            sec = resolve_domain_module("legal_docs", "sec_filings")
        except _ModuleNotFound:
            return _data_module_unavailable(name, "legal_docs")
        data = await sec.search_filings(ticker=ticker, form_type=form_type, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": True, "data": data, "ticker": ticker.upper()}, indent=2
                    ),
                }
            ],
            "isError": False,
        }

    if name == "pry_legal_sanctions":
        screen = arguments.get("name", "")
        if not screen:
            return _missing_arg(name, "name")
        try:
            sanctions = resolve_domain_module("legal_docs", "sanctions")
        except _ModuleNotFound:
            return _data_module_unavailable(name, "legal_docs")
        data = await sanctions.screen_name(name=screen)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": data, "name": screen}, indent=2),
                }
            ],
            "isError": False,
        }

    return None
