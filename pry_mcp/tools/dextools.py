# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""MCP surface for our own Dextools store: `dextools_search`.

Same semantics as `pry dextools search`: rows carry the `source_url` that
produced them; an empty store is a typed `unavailable` refusal, never `[]`.
"""

from __future__ import annotations

from typing import Any

from pry.datasources.dextools_store import search_or_refusal

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "dextools_search",
        "description": (
            "Search the locally ingested Dextools token store (scraped from allowed "
            "public pages with robots.txt respected). Matches symbol, name or address. "
            "Every row includes source_url and fetched_at; missing fields are null, "
            "never fabricated. Returns a typed `unavailable` refusal when the store "
            "is empty. Use it to resolve a ticker or contract address to the token's "
            'on-chain identity before a deeper lookup. Example: query="pepe", '
            'chain="ethereum" returns the stored Pepe rows with their source_url, '
            'or query="0x6982..." to match by address.'
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Symbol, name fragment or address."},
                "chain": {"type": "string", "description": "Optional chain slug filter."},
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 200,
                    "description": "Maximum rows to return (1-200, default 20).",
                },
            },
            "required": ["query"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "`ok` when rows were found, `unavailable` when the store has no match.",
                },
                "count": {"type": "integer", "description": "Rows returned."},
                "results": {
                    "type": "array",
                    "description": "Matching store rows; absent fields are null, never fabricated.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "name": {"type": "string"},
                            "address": {"type": "string"},
                            "chain": {"type": "string"},
                            "source_url": {
                                "type": "string",
                                "description": "Public page the row was scraped from.",
                            },
                            "fetched_at": {"type": "string"},
                        },
                    },
                },
            },
        },
        "annotations": {
            "title": "Dextools token store search",
            # Reads a local ingested store; never writes, never reaches a
            # third-party API, and the same query returns the same rows.
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }
]


async def call_dextools_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch `dextools_search`; returns None for tools owned by other executors."""
    if name != "dextools_search":
        return None
    query = str(arguments.get("query") or "").strip()
    if not query:
        return {"error": "missing_argument", "detail": "query is required"}
    limit = int(arguments.get("limit") or 20)
    chain = arguments.get("chain") or None
    return search_or_refusal(query, chain=str(chain) if chain else None, limit=limit)
