"""Pry - bodies of the ``pry://`` resources.

One builder per resource URI, each returning the JSON/text the client reads.
A resource read is a protocol call: the client expects a well-formed result, so
a failed read degrades to an error payload (logged) instead of raising out of
the handler.

Note: ``pry_mcp.resources_prompts`` holds the prompt DEFINITIONS; the
``pry_mcp.resources.prompts`` module next door builds the prompt MESSAGES.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
from typing import Any

from pry_mcp.constants import MCP_PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION
from pry_mcp.resources_defs import DATA_DOMAINS

logger = logging.getLogger(__name__)

# These builders read in-memory registries and JSON-serialize them, so the
# realistic failures are a missing or relocated module (ImportError), an
# unexpected shape in the returned registry (AttributeError/KeyError/TypeError),
# and a non-serializable object reaching json.dumps (TypeError). There is no
# json DECODE on this path. A broad tuple is the honest boundary: the
# alternative is a resource read that raises straight through the MCP server
# and breaks the protocol response instead of degrading to an error message.
RESOURCE_READ_ERRORS = (Exception,)


def _error_json(what: str, exc: BaseException) -> str:
    """JSON error body for a resource read that could not be built."""
    return json.dumps({"error": f"Could not load {what}: {exc}"})


def _catalog_text(uri: str) -> str:
    """Template catalog grouped by category."""
    try:
        from pry.commerce.template_engine import list_templates

        templates = list_templates()
        categories: dict[str, list[str]] = {}
        for t in templates:
            categories.setdefault(t.get("category", "general"), []).append(
                t.get("template_id", "unknown")
            )
        return json.dumps(
            {
                "total_templates": len(templates),
                "categories": categories,
                "note": "Use pry_search_templates to query dynamically.",
            },
            indent=2,
        )
    except RESOURCE_READ_ERRORS as e:
        logger.warning(
            "mcp_resource_template_catalog_failed",
            extra={"uri": uri, "error": str(e), "error_type": type(e).__name__},
            exc_info=True,
        )
        return _error_json("template catalog", e)


def _stats_text(tools: dict[str, Any], resources: dict[str, Any], prompts: dict[str, Any]) -> str:
    """Server identity and registry sizes."""
    return json.dumps(
        {
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "protocol_version": MCP_PROTOCOL_VERSION,
            "tools_count": len(tools),
            "resources_count": len(resources),
            "prompts_count": len(prompts),
        },
        indent=2,
    )


def _x402_text(uri: str) -> str:
    """x402 pricing statistics."""
    try:
        from pry.payments.x402 import X402Handler

        return json.dumps(X402Handler().get_stats(), indent=2)
    except RESOURCE_READ_ERRORS as e:
        logger.warning(
            "mcp_resource_x402_pricing_failed",
            extra={"uri": uri, "error": str(e), "error_type": type(e).__name__},
            exc_info=True,
        )
        return _error_json("x402 pricing", e)


def _referrals_text(uri: str) -> str:
    """Referral program catalog."""
    try:
        from pry.commerce.referrals import ReferralTracker

        return json.dumps(ReferralTracker().get_catalog(), indent=2)
    except RESOURCE_READ_ERRORS as e:
        logger.warning(
            "mcp_resource_referrals_failed",
            extra={"uri": uri, "error": str(e), "error_type": type(e).__name__},
            exc_info=True,
        )
        return _error_json("referrals", e)


def _coverage_text(uri: str) -> str:
    """Site catalog coverage, counted by data domain, method and anti-bot."""
    try:
        from site_catalog import SiteCatalog

        catalog = SiteCatalog().coverage()
    except RESOURCE_READ_ERRORS as e:
        logger.warning(
            "mcp_resource_coverage_failed",
            extra={"uri": uri, "error": str(e), "error_type": type(e).__name__},
            exc_info=True,
        )
        return _error_json("site catalog coverage", e)
    by_domain: dict[str, int] = {}
    by_method: dict[str, int] = {}
    by_anti_bot: dict[str, int] = {}
    for entry in catalog:
        domain = entry.get("data_domain", "unknown")
        method = entry.get("method", "unknown")
        anti_bot = entry.get("anti_bot", "unknown")
        by_domain[domain] = by_domain.get(domain, 0) + 1
        by_method[method] = by_method.get(method, 0) + 1
        by_anti_bot[anti_bot] = by_anti_bot.get(anti_bot, 0) + 1
    return json.dumps(
        {
            "total_sites": len(catalog),
            "by_data_domain": by_domain,
            "by_method": by_method,
            "by_anti_bot": by_anti_bot,
            "note": "Use pry://domains for the data-domain list.",
        },
        indent=2,
    )


def _domains_text() -> str:
    """The static data-domain list (no I/O, so no failure path to swallow)."""
    return json.dumps({"count": len(DATA_DOMAINS), "domains": DATA_DOMAINS}, indent=2)


_BUILDERS: dict[str, Any] = {
    "pry://catalog": _catalog_text,
    "pry://x402/pricing": _x402_text,
    "pry://referrals": _referrals_text,
    "pry://coverage": _coverage_text,
}


def resource_text(
    uri: str,
    resources: dict[str, Any],
    prompts: dict[str, Any],
    tools: dict[str, Any],
) -> str:
    """Return the body of ``uri``; unknown URIs get the placeholder line."""
    if uri == "pry://stats":
        return _stats_text(tools, resources, prompts)
    if uri == "pry://domains":
        return _domains_text()
    builder = _BUILDERS.get(uri)
    if builder is None:
        return f"Resource {uri} (placeholder)"
    return builder(uri)
