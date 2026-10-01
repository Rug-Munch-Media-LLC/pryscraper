"""Pry - MCP tool definitions: jobs / salary tools and dispatcher..

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

from ._common import _data_module_unavailable, _missing_arg, _ModuleNotFound, resolve_domain_module

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_jobs_list",
        "description": (
            "List current job postings for a company from its applicant-tracking system "
            "(Greenhouse, Lever, Ashby, or Workday), returning normalized titles, locations, "
            "remote flags, and application URLs. Use for talent-market intel or recruitment "
            "pipelines, e.g. 'what engineering roles is Stripe hiring for?'. Reads the free, "
            "public, keyless JSON boards; never raises and returns an empty list when the "
            "board is unreachable or the company slug is unknown."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company slug on the ATS board, e.g. 'stripe'",
                },
                "board": {
                    "type": "string",
                    "enum": ["greenhouse", "lever", "ashby", "workday"],
                    "default": "greenhouse",
                    "description": "ATS board to query (default: greenhouse)",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of listings to return (default: 50)",
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
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "company": {"type": "string"},
                            "location": {"type": "string"},
                            "remote": {"type": "boolean"},
                            "url": {"type": "string"},
                            "posted_at": {"type": "string"},
                        },
                    },
                },
                "board": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_jobs_salary",
        "description": (
            "Get per-level salary bands (total compensation, base, stock, bonus) for a "
            "company and role from Levels.fyi's public embedded data. Use to benchmark "
            "compensation offers or market rates, e.g. 'what does Google pay software "
            "engineers at L5?'. Scrapes the free Levels.fyi page with no auth; never "
            "raises and returns an empty object when the company or role is not found."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company slug, e.g. 'google'",
                },
                "role": {
                    "type": "string",
                    "default": "software_engineer",
                    "description": "Role slug, e.g. 'software_engineer', 'product_manager'",
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
                        "role": {"type": "string"},
                        "levels": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "level": {"type": "string"},
                                    "total_comp": {"type": "number"},
                                    "base": {"type": "number"},
                                    "stock": {"type": "number"},
                                    "bonus": {"type": "number"},
                                },
                            },
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
]


async def call_jobs_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch jobs/salary MCP tools to their ``jobs`` handlers (guarded)."""
    if name == "pry_jobs_list":
        company = arguments.get("company", "")
        if not company:
            return _missing_arg(name, "company")
        board = arguments.get("board", "greenhouse")
        limit = int(arguments.get("limit", 50))
        try:
            ats = resolve_domain_module("jobs", "ats")
        except _ModuleNotFound:
            return _data_module_unavailable(name, "jobs")
        data = await ats.list_jobs(company, board=board, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": True, "data": data, "board": board, "company": company},
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    if name == "pry_jobs_salary":
        company = arguments.get("company", "")
        if not company:
            return _missing_arg(name, "company")
        role = arguments.get("role", "software_engineer")
        try:
            salary = resolve_domain_module("jobs", "salary")
        except _ModuleNotFound:
            return _data_module_unavailable(name, "jobs")
        salary_data = await salary.get_salary(company, role=role)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": bool(salary_data), "data": salary_data, "company": company},
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    return None
