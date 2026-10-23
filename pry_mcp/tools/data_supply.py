"""Pry - MCP tool definitions: supply data tools (imports, firmographics).

Split from the former ``pry_mcp/tools/data.py`` god file. Holds the
supply-domain tool schemas (``PRY_TOOLS``), the guarded candidate registry
(``_SUPPLY_TOOL_FNS``), and the ``call_supply_tool`` dispatcher.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from ._common import _call_domain_dispatcher
from ._kwargs_data import _broad_domain_tool_kwargs

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_imports",
        "description": (
            "Get U.S. customs import records for a company: shipment dates, "
            "commodity descriptions, suppliers, and origin countries. Use to "
            "size a competitor's supply chain or vet suppliers, e.g. call with "
            "company='Tesla Inc' for recent bill-of-lading entries with "
            "quantities."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name or importer-of-record, e.g. 'Tesla Inc'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of shipment records (default: 20)",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of shipment records to skip before the page (pagination)",
                },
            },
            "required": ["company"],
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
                            "consignee": {"type": "string"},
                            "supplier": {"type": "string"},
                            "commodity": {"type": "string"},
                            "origin_country": {"type": "string"},
                            "arrival_date": {"type": "string"},
                            "value_usd": {"type": "number"},
                        },
                    },
                },
                "company": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_firmographics",
        "description": (
            "Get firmographic data for a company: employee count band, revenue "
            "range, founding year, headquarters, industry, and company type. "
            "Use to segment leads or enrich CRM records, e.g. call with "
            "company='Rug Munch Media' for the standard firmographic profile "
            "with confidence scores."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name, e.g. 'Rug Munch Media'",
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
                        "employees_band": {"type": "string"},
                        "revenue_range_usd": {"type": "string"},
                        "founded_year": {"type": "integer"},
                        "headquarters": {"type": "string"},
                        "industry": {"type": "string"},
                        "company_type": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]

# ── Supply candidate registry (guarded) ───────────────────────────────
# Candidate public function names for the supply_data package (``imports``,
# ``firmographics``). These land from parallel agents; every import is guarded
# so the dispatcher degrades gracefully (a readable message) if a module has
# not landed yet.
_SUPPLY_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_imports": (("imports", ("get_import_records", "import_records", "get_imports")),),
    "pry_firmographics": (
        (
            "firmographics",
            (
                "get_company_firmographics",
                "company_firmographics",
                "get_firmographics",
            ),
        ),
    ),
}


async def call_supply_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch supply-data MCP tools to their ``supply_data`` handlers (guarded).

    The ``supply_data`` subpackage (``imports``, ``firmographics``) is built
    in parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-supply tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "supply_data",
        _SUPPLY_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_imports": "company", "pry_firmographics": "company"},
    )
