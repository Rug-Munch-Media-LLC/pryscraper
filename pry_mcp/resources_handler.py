"""Pry - MCP resource / prompt / completion handlers.

ResourceHandler class implementing the read/prompt/completion protocol
methods for the MCP server.

Split from resources.py.
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

# MCP resource reads are protocol calls: the client expects a well-formed
# result, so a failed read must be reported as an error payload rather than
# raised out of the handler. These helpers build in-process dicts/lists from
# in-memory registries, so the realistic failures are NOT json decode errors
# (nothing is decoded) and NOT bare ValueError. They are: a missing or
# relocated module (ImportError), an unexpected attribute/shape in the
# returned registry (AttributeError/KeyError/TypeError), and a non-serializable
# object reaching json.dumps (TypeError). A bare `except Exception` is the
# honest boundary here — the alternative is a resource read that raises
# AttributeError straight through the MCP server and breaks the protocol
# response instead of degrading to an error message.
_RESOURCE_READ_EXCEPTIONS = (Exception,)


class ResourceHandler:
    """Resource / prompt / completion handlers for the MCP server.

    Extracted from ``FallbackMCPServer`` to reduce the god-class. Holds the
    live ``resources`` / ``prompts`` registries (and ``tools`` for the
    ``pry://stats`` resource) and implements the read/prompt/completion
    protocol methods.
    """

    def __init__(
        self,
        resources: dict[str, dict[str, Any]],
        prompts: dict[str, dict[str, Any]],
        tools: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.resources = resources
        self.prompts = prompts
        self.tools = tools if tools is not None else {}

    def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource. Returns proper MCP-compliant response."""
        if uri not in self.resources:
            return {"error": {"code": -32602, "message": f"Resource not found: {uri}"}}
        res = self.resources[uri]
        text = self._resource_text(uri)
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": res.get("mimeType", "text/plain"),
                    "text": text,
                }
            ],
        }

    def _resource_text(self, uri: str) -> str:
        """Generate resource contents without external I/O."""
        if uri == "pry://catalog":
            try:
                from pry.commerce.template_engine import list_templates

                templates = list_templates()
                categories: dict[str, list[str]] = {}
                for t in templates:
                    cat = t.get("category", "general")
                    categories.setdefault(cat, []).append(t.get("template_id", "unknown"))
                return json.dumps(
                    {
                        "total_templates": len(templates),
                        "categories": categories,
                        "note": "Use pry_search_templates to query dynamically.",
                    },
                    indent=2,
                )
            except _RESOURCE_READ_EXCEPTIONS as e:
                logger.warning(
                    "mcp_resource_template_catalog_failed",
                    extra={"uri": uri, "error": str(e), "error_type": type(e).__name__},
                    exc_info=True,
                )
                return json.dumps({"error": f"Could not load template catalog: {e}"})
        if uri == "pry://stats":
            return json.dumps(
                {
                    "server": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "protocol_version": MCP_PROTOCOL_VERSION,
                    "tools_count": len(self.tools),
                    "resources_count": len(self.resources),
                    "prompts_count": len(self.prompts),
                },
                indent=2,
            )
        if uri == "pry://x402/pricing":
            try:
                from pry.payments.x402 import X402Handler

                return json.dumps(X402Handler().get_stats(), indent=2)
            except _RESOURCE_READ_EXCEPTIONS as e:
                logger.warning(
                    "mcp_resource_x402_pricing_failed",
                    extra={"uri": uri, "error": str(e), "error_type": type(e).__name__},
                    exc_info=True,
                )
                return json.dumps({"error": f"Could not load x402 pricing: {e}"})
        if uri == "pry://referrals":
            try:
                from pry.commerce.referrals import ReferralTracker

                return json.dumps(ReferralTracker().get_catalog(), indent=2)
            except _RESOURCE_READ_EXCEPTIONS as e:
                logger.warning(
                    "mcp_resource_referrals_failed",
                    extra={"uri": uri, "error": str(e), "error_type": type(e).__name__},
                    exc_info=True,
                )
                return json.dumps({"error": f"Could not load referrals: {e}"})
        if uri == "pry://coverage":
            try:
                from site_catalog import SiteCatalog

                catalog = SiteCatalog().coverage()
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
            except (json.JSONDecodeError, ValueError, ImportError) as e:
                return json.dumps({"error": f"Could not load site catalog coverage: {e}"})
        if uri == "pry://domains":
            try:
                return json.dumps(
                    {"count": len(DATA_DOMAINS), "domains": DATA_DOMAINS},
                    indent=2,
                )
            except (json.JSONDecodeError, ValueError, ImportError) as e:
                return json.dumps({"error": f"Could not load data domains: {e}"})
        return f"Resource {uri} (placeholder)"

    def get_prompt(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Get a prompt. Returns proper MCP-compliant response."""
        if name not in self.prompts:
            return {"error": {"code": -32602, "message": f"Prompt not found: {name}"}}
        prompt = self.prompts[name]
        messages = self._prompt_messages(name, arguments)
        return {
            "description": prompt.get("description", ""),
            "messages": messages,
        }

    def _prompt_messages(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Build real prompt messages for named prompts."""
        if name == "research_company":
            company = arguments.get("company_name", "the company")
            website = arguments.get("website", "")
            return [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Research {company}. "
                            f"{'Start by scraping ' + website + '. ' if website else ''}"
                            "Use pry_scrape and pry_enrich to gather data, then summarize: "
                            "what they do, target market, key products, competitive positioning, "
                            "and any risks or opportunities."
                        ),
                    },
                }
            ]
        if name == "compare_products":
            query = arguments.get("product_query", "the product")
            sites = arguments.get("sites", [])
            return [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Compare prices and details for '{query}' across {', '.join(sites)}. "
                            "Use pry_template with amazon-product, walmart-product, etc. "
                            "Return a side-by-side comparison table."
                        ),
                    },
                }
            ]
        if name == "extract_contacts":
            url = arguments.get("url", "")
            max_pages = arguments.get("max_pages", 20)
            return [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Extract all contact information from {url}. "
                            f"Crawl up to {max_pages} pages. "
                            "Use pry_crawl and regex to find emails, phones, and social profiles."
                        ),
                    },
                }
            ]
        if name == "monitor_competitor":
            url = arguments.get("url", "")
            what = arguments.get("what_to_track", "changes")
            webhook = arguments.get("webhook_url", "")
            return [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Set up monitoring for {url}. Track {what}. "
                            f"{'Notify via webhook: ' + webhook + '. ' if webhook else ''}"
                            "Use pry_monitor."
                        ),
                    },
                }
            ]
        if name == "analyze_article":
            url = arguments.get("url", "")
            focus = arguments.get("focus", "")
            return [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Scrape and analyze this article: {url}. "
                            f"{'Focus on: ' + focus + '. ' if focus else ''}"
                            "Summarize key points, sentiment, entities, and claims."
                        ),
                    },
                }
            ]
        if name == "extract_table":
            url = arguments.get("url", "")
            desc = arguments.get("table_description", "")
            return [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Extract the data table from {url}. Table: {desc}. "
                            "Use pry_extract with CSS selectors or pry_scrape + structured output."
                        ),
                    },
                }
            ]
        if name == "scrape_with_schema":
            url = arguments.get("url", "")
            fields = arguments.get("fields", "")
            return [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Scrape {url} and extract these fields: {fields}. "
                            "Use pry_extract with a custom JSON schema."
                        ),
                    },
                }
            ]
        arg_text = ", ".join(f"{k}={v}" for k, v in arguments.items())
        return [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"Execute the {self.prompts[name].get('title', name)} prompt with arguments: {arg_text}",
                },
            }
        ]

    def complete(self, ref: dict[str, Any], argument: dict[str, Any]) -> dict[str, Any]:
        """Provide argument completion suggestions."""
        ref_type = ref.get("type", "")
        ref_name = ref.get("name", "") or ref.get("uri", "")
        arg_name = argument.get("name", "")
        arg_value = argument.get("value", "")
        values: list[str] = []
        if ref_type == "ref/prompt" and ref_name == "extract_contacts" and arg_name == "max_pages":
            values = ["10", "20", "50", "100"]
        elif ref_type == "ref/tool" and arg_name == "template_id":
            try:
                from pry.commerce.template_engine import list_templates

                templates = list_templates()
                values = [
                    t["template_id"]
                    for t in templates
                    if arg_value.lower() in t.get("template_id", "").lower()
                ][:10]
            except Exception as e:
                # An empty suggestion list is indistinguishable from "no
                # matching template" at the protocol level, so a real failure
                # (import error, registry shape change) would be reported to
                # the user as a working autocomplete with no matches. Log it
                # so the failure is visible in the MCP server log.
                logger.warning(
                    "mcp_completion_template_id_failed",
                    extra={
                        "ref_name": ref_name,
                        "arg_value": arg_value,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                    exc_info=True,
                )
                values = []
        elif ref_type == "ref/tool" and arg_name == "url":
            values = []
        elif arg_name in ("format", "mime_type"):
            values = ["json", "csv", "markdown", "html"]
        return {"values": values}
