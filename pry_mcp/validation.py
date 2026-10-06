"""Pry - MCP tool argument validation seam.

Audit item #24: incoming MCP tool arguments are unvalidated JSON dicts that
flow straight into business functions. This module adds a minimal validation
seam in front of the combined executor:

- ``TOOL_REQUIREMENTS`` — an allowlist table for the TOP 20 highest-risk tools
  (scrape, crawl, monitor, batch/actor ops, pay-related), derived mechanically
  from each tool's own ``inputSchema`` in ``pry_mcp.tools.PRY_TOOLS``
  (required fields + expected primitive types).
- ``validate_tool_args`` — raises ``ToolArgError`` when args are not a dict,
  a required field is missing, or a required field has the wrong primitive
  type (str→int coercion where safe). Unknown/extra fields pass through.
- ``dispatch_safely`` — wraps an executor call, converting validation and
  execution failures into structured error dicts instead of propagating.

Tools not in the table pass through unvalidated: the table is an allowlist
for enforcement, not a gate on every tool.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# JSON-schema primitive -> Python type used for required-field checks.
# ``bool`` is checked before ``int`` (bool is a subclass of int).
_PRIMITIVE_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
}

# TOP 20 highest-risk tools: scrape/crawl/extract/template/monitor/screenshot/
# parse/enrich (external-fetch surface), actor batch runs, pay/billing tools,
# and the crypto/marketplace scrapers. Each entry is copied mechanically from
# the tool's ``inputSchema`` in pry_mcp.tools.PRY_TOOLS: (field, python_type)
# for every REQUIRED field. Tools with no required fields get an empty tuple
# (they are still gated on dict-ness by validate_tool_args).
TOOL_REQUIREMENTS: dict[str, tuple[tuple[str, type], ...]] = {
    # --- scrape / crawl / extract / template / monitor (external fetch) ---
    "pry_scrape": (("url", str),),
    "pry_crawl": (("url", str),),
    "pry_extract": (("url", str), ("schema", dict)),
    "pry_template": (("template_id", str), ("url", str)),
    "pry_search_templates": (("q", str),),
    "pry_monitor": (("name", str), ("url", str)),
    "pry_screenshot": (("url", str),),
    "pry_parse_document": (("url", str),),
    "pry_enrich": (("url", str),),
    # --- batch / actor ops ---
    "pry_actor_run": (("actor", str), ("urls", list)),
    # --- pay-related ---
    "pry_buy_pack": (("pack_id", str),),
    "pry_balance": (),
    "pry_x402_pricing": (),
    # --- crypto / marketplace scrapers ---
    "pry_token_security": (("chain", str), ("address", str)),
    "pry_token_launches": (),
    "pry_cex_listings": (),
    "pry_kol_leaderboards": (),
    "pry_amazon_product": (("asin", str),),
    "pry_amazon_search": (("query", str),),
    "pry_walmart_product": (("product_id", str),),
}


class ToolArgError(Exception):
    """Raised when MCP tool arguments fail validation."""


def _coerce_str_to_int(value: Any) -> int | None:
    """Coerce a str to int when it is a clean integer literal, else None."""
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return int(stripped)
        except ValueError as e:
            logger.warning(
                "suppressed %s in _coerce_str_to_int (validation.py:88): %s",
                "ValueError",
                e,
            )
            return None
    return None


def validate_tool_args(tool_name: str, args: Any) -> dict[str, Any]:
    """Validate MCP tool arguments against ``TOOL_REQUIREMENTS``.

    Returns a (possibly coerced) copy of the args dict. Raises ``ToolArgError``
    when args are not a dict, a required field is missing, or a required field
    has the wrong primitive type (str→int coercion applied where safe).
    Unknown/extra fields pass through untouched. Tools not in the table are
    not gated: dict args pass through as-is, non-dict args become ``{}``.
    """
    requirements = TOOL_REQUIREMENTS.get(tool_name)
    if requirements is None:
        # Unknown tool: allowlist for enforcement, not a gate — pass through.
        return dict(args) if isinstance(args, dict) else {}

    if not isinstance(args, dict):
        raise ToolArgError(
            f"Tool {tool_name}: arguments must be a JSON object, got {type(args).__name__}"
        )

    validated: dict[str, Any] = dict(args)
    for field, expected in requirements:
        if field not in validated:
            raise ToolArgError(f"Tool {tool_name}: missing required argument '{field}'")
        value = validated[field]
        # bool must be checked before int (bool subclasses int).
        if expected is bool:
            ok = isinstance(value, bool)
        elif expected is int:
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif expected is float:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, expected)
        if ok:
            continue
        if expected is int:
            coerced = _coerce_str_to_int(value)
            if coerced is not None:
                validated[field] = coerced
                continue
        raise ToolArgError(
            f"Tool {tool_name}: argument '{field}' must be "
            f"{expected.__name__}, got {type(value).__name__}"
        )
    return validated


async def dispatch_safely(fn: Any, tool_name: str, args: Any) -> dict[str, Any]:
    """Run an MCP tool executor with validation, never propagating exceptions.

    Validates ``args`` via ``validate_tool_args`` (invalid args →
    ``invalid_args`` error dict), then awaits ``fn(tool_name, args)``.
    Any ``Exception`` (never ``BaseException``) raised by the tool becomes a
    ``tool_failed`` error dict. Returns the tool result on success.
    """
    try:
        validated = validate_tool_args(tool_name, args)
    except ToolArgError as exc:
        logger.warning("mcp_tool_invalid_args", extra={"tool": tool_name, "error": str(exc)})
        return {"error": {"code": "invalid_args", "message": str(exc)}}
    try:
        result = fn(tool_name, validated)
        if hasattr(result, "__await__"):
            result = await result
        return result
    except Exception as exc:  # noqa: BLE001 — structured error, not a crash
        logger.warning("mcp_tool_failed", extra={"tool": tool_name, "error": str(exc)})
        return {
            "error": {
                "code": "tool_failed",
                "message": f"Tool {tool_name} failed: {exc}",
            }
        }
