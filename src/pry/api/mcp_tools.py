# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Dynamic MCP tool generation for Pry.

Auto-generates MCP tools from FastAPI router definitions so every endpoint
is discoverable via MCP without manual tool definitions.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def discover_api_tools() -> list[dict[str, Any]]:
    """Discover all API endpoints and generate MCP tool definitions."""
    from pry.api.api import app

    tools: list[dict[str, Any]] = []

    for route in app.routes:
        if not hasattr(route, "methods") or not hasattr(route, "path"):
            continue
        if not route.methods or ("GET" not in route.methods and "POST" not in route.methods):
            continue

        # Skip internal/docs endpoints
        if route.path in {"/openapi.json", "/docs", "/redoc", "/"}:
            continue

        method = "POST" if "POST" in route.methods else "GET"
        tool_name = _path_to_tool_name(route.path, method)

        # Build input schema from path/query params
        properties: dict[str, Any] = {}
        required: list[str] = []

        if hasattr(route, "dependant"):
            for param in route.dependant.query_params:
                properties[param.name] = {
                    "type": _type_to_json_schema(param.type_),
                    "description": param.field_info.description or f"Query parameter {param.name}",
                }
                if param.required:
                    required.append(param.name)

        tools.append(
            {
                "name": tool_name,
                "description": _generate_description(route),
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
                "method": method,
                "path": route.path,
            }
        )

    return tools


def _path_to_tool_name(path: str, method: str) -> str:
    """Convert API path to MCP tool name."""
    # Remove /v1/ prefix and convert to snake_case
    clean = path.replace("/v1/", "").replace("/", "_").replace("-", "_")
    # Remove leading/trailing underscores
    clean = clean.strip("_")
    # Prefix with pry_
    return f"pry_{clean}" if not clean.startswith("pry") else clean


def _type_to_json_schema(type_: Any) -> str:
    """Convert Python type to JSON schema type."""

    origin = getattr(type_, "__origin__", None)
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    if type_ is int:
        return "integer"
    if type_ is float:
        return "number"
    if type_ is bool:
        return "boolean"
    return "string"


def _generate_description(route: Any) -> str:
    """Generate a description for an API route."""
    summary = getattr(route, "summary", "") or ""
    description = getattr(route, "description", "") or ""
    return summary or description or f"Call {route.path}"
