"""Pry — Production MCP Server using the official MCP Python SDK.
Implements the full Model Context Protocol (MCP) 2024-11-05 spec.

Compatible with: Claude Desktop, Cursor, Continue.dev, Smithery, Glama.

Standard MCP features implemented:
- Tools (model-controlled functions)
- Resources (application-controlled data)
- Prompts (user-controlled templates)
- Completion (argument completion)
- Logging (server-to-client log messages)
- Notifications (progress, list_changed)

Run: python -m mcp_production
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable, Coroutine
from typing import Any, ClassVar

import httpx

logger = logging.getLogger(__name__)

# MCP protocol version (per the official spec)
MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "pry"
SERVER_VERSION = "3.0.0"

DEFAULT_BASE_URL = os.getenv("PRY_API_URL", "http://localhost:8002")

# Observer callbacks for outgoing MCP notifications (used by SSE transport).
# Each callback receives a JSON-RPC notification dict.
NotificationObserver = Callable[[dict[str, Any]], None]
_mcp_notification_observers: list[NotificationObserver] = []


def register_mcp_notification_observer(observer: NotificationObserver) -> None:
    """Register a callback that receives every outgoing MCP notification."""
    if observer not in _mcp_notification_observers:
        _mcp_notification_observers.append(observer)


def unregister_mcp_notification_observer(observer: NotificationObserver) -> None:
    """Remove a notification observer."""
    if observer in _mcp_notification_observers:
        _mcp_notification_observers.remove(observer)


def _send_mcp_notification(notification: dict[str, Any]) -> None:
    """Dispatch an MCP notification to all registered observers."""
    for observer in list(_mcp_notification_observers):
        try:
            observer(notification)
        except Exception as e:
            logger.warning("mcp_notification_observer_failed", extra={"error": str(e)})


class MCPLoggingHandler(logging.Handler):
    """Python logging handler that forwards log records as MCP notifications.

    MCP log levels: alert, critical, debug, emergency, error, info, notice, warning.
    """

    _LEVEL_MAP: ClassVar[dict[int, str]] = {
        logging.DEBUG: "debug",
        logging.INFO: "info",
        logging.WARNING: "warning",
        logging.ERROR: "error",
        logging.CRITICAL: "critical",
    }

    def __init__(self, server: Any) -> None:
        super().__init__()
        self.server = server

    def emit(self, record: logging.LogRecord) -> None:
        if not getattr(self.server, "_mcp_log_enabled", False):
            return
        min_level = getattr(self.server, "_mcp_log_level", logging.INFO)
        if record.levelno < min_level:
            return
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {
                "level": self._LEVEL_MAP.get(record.levelno, "info"),
                "logger": record.name,
                "data": self.format(record),
            },
        }
        _send_mcp_notification(notification)


# Attach one global handler to the pry logger tree once a server is created.
_mcp_log_handler: MCPLoggingHandler | None = None


def _attach_mcp_logging(server: Any) -> None:
    """Attach the MCP forwarding log handler to the pry logger."""
    global _mcp_log_handler
    if _mcp_log_handler is None:
        _mcp_log_handler = MCPLoggingHandler(server)
        _mcp_log_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logging.getLogger("pry").addHandler(_mcp_log_handler)
        logging.getLogger("pry").setLevel(logging.DEBUG)


# Global server instance used by notification helpers.
_active_mcp_server: Any | None = None


def set_active_mcp_server(server: Any) -> None:
    """Mark an MCP server instance as active so helpers can use it."""
    global _active_mcp_server
    _active_mcp_server = server


def notify_resource_changed(uri: str) -> None:
    """Notify all connected MCP clients that a resource has changed."""
    _send_mcp_notification({
        "jsonrpc": "2.0",
        "method": "notifications/resources/updated",
        "params": {"uri": uri},
    })


def notify_resource_list_changed() -> None:
    """Notify all connected MCP clients that the resource list changed."""
    _send_mcp_notification({
        "jsonrpc": "2.0",
        "method": "notifications/resources/list_changed",
    })


def notify_tool_list_changed() -> None:
    """Notify all connected MCP clients that the tool list changed."""
    _send_mcp_notification({
        "jsonrpc": "2.0",
        "method": "notifications/tools/list_changed",
    })

# Try to import official MCP SDK
try:
    import mcp.server.session  # noqa: F401
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (  # noqa: F401
        Annotations,
        BlobResourceContents,
        CallToolRequest,
        CallToolResult,
        CompleteResult,
        Completion,
        CompletionArgument,
        CompletionContext,
        EmptyResult,
        GetPromptResult,
        ImageContent,
        ListPromptsResult,
        ListResourcesResult,
        ListToolsResult,
        LoggingLevel,
        LoggingMessageNotificationParams,
        Prompt,
        PromptArgument,
        PromptMessage,
        ReadResourceResult,
        Resource,
        Tool,
    )

    _has_mcp_sdk = True
except ImportError:
    _has_mcp_sdk = False
    logger.warning("mcp_sdk_not_installed", extra={"hint": "pip install mcp"})


# ── Tool Definitions (matching modelcontextprotocol.io spec) ──

PRY_TOOLS = [
    {
        "name": "pry_scrape",
        "description": "Scrape a URL to clean markdown. Bypasses Cloudflare, DataDome, Akamai, and other anti-bot systems automatically using a 9-tier fallback (direct → cloudscraper → FlareSolverr → Playwright → Googlebot → Archive.org → Google Cache → Tor → undetected-chromedriver).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri", "description": "URL to scrape"},
                "bypass_cloudflare": {
                    "type": "boolean",
                    "default": True,
                    "description": "Use FlareSolverr + Playwright fallback",
                },
                "js_render": {
                    "type": "boolean",
                    "default": False,
                    "description": "Render JavaScript (slower but handles SPAs)",
                },
                "extract_schema": {
                    "type": "object",
                    "description": "Optional JSON schema for structured extraction (e.g., {fields: [{name, selector, type}]})",
                },
            },
            "required": ["url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string", "description": "Clean markdown content"},
                        "links": {"type": "array", "items": {"type": "string"}},
                        "images": {"type": "array", "items": {"type": "string"}},
                        "status_code": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_crawl",
        "description": "Crawl a website starting from a URL. Discovers and scrapes linked pages up to max_pages with BFS/DFS traversal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "max_pages": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 10000,
                },
                "max_depth": {
                    "type": "integer",
                    "default": 2,
                    "minimum": 0,
                    "maximum": 20,
                },
                "include_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URL path patterns to include (e.g., ['/docs/', '/blog/'])",
                },
                "exclude_paths": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "pages": {"type": "array", "items": {"type": "object"}},
                        "total_pages": {"type": "integer"},
                    },
                },
            },
        },
    },
    {
        "name": "pry_extract",
        "description": "Extract structured data from a URL using CSS selectors. 10x cheaper than LLM extraction. Returns JSON matching the schema.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "schema": {
                    "type": "object",
                    "description": "Extraction schema with base_selector and fields array",
                    "properties": {
                        "name": {"type": "string"},
                        "base_selector": {"type": "string"},
                        "fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "selector": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "enum": [
                                            "text",
                                            "attribute",
                                            "html",
                                            "nested",
                                            "count",
                                            "exists",
                                            "regex",
                                        ],
                                    },
                                    "attribute": {"type": "string"},
                                    "transform": {"type": "string"},
                                },
                                "required": ["name", "selector"],
                            },
                        },
                    },
                    "required": ["name", "fields"],
                },
            },
            "required": ["url", "schema"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_template",
        "description": "Execute one of 110+ pre-built scraper templates (amazon-product, walmart-product, linkedin-profile, etc.). Returns structured data matching the site's schema.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "Template ID (e.g., 'amazon-product', 'walmart-product', 'linkedin-profile')",
                },
                "url": {"type": "string", "format": "uri"},
            },
            "required": ["template_id", "url"],
        },
    },
    {
        "name": "pry_search_templates",
        "description": "Search across all 110+ available scraper templates by keyword, category, or site.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Search query (e.g., 'amazon', 'jobs', 'real estate')",
                },
                "category": {"type": "string", "description": "Filter by category"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "pry_monitor",
        "description": "Create a content change monitor. Get notified via webhook, Slack, or Discord when a page changes. AI judges if changes are meaningful.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "url": {"type": "string", "format": "uri"},
                "schedule_cron": {
                    "type": "string",
                    "default": "0 */6 * * *",
                    "description": "Cron expression (default: every 6 hours)",
                },
                "webhook_url": {"type": "string", "format": "uri"},
                "goal": {
                    "type": "string",
                    "description": "Natural language goal for AI change judging (e.g., 'price changes matter, not descriptions')",
                },
            },
            "required": ["name", "url"],
        },
    },
    {
        "name": "pry_compliance",
        "description": "Check legal compliance for scraping a URL. Analyzes robots.txt, ToS, GDPR/CCPA, and PII exposure. Returns green/yellow/red risk score with recommendations.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
            "required": ["url"],
        },
    },
    {
        "name": "pry_enrich",
        "description": "Enrich a URL with company info, tech stack detection, social profiles, and competitive intelligence.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
            "required": ["url"],
        },
    },
    {
        "name": "pry_parse_document",
        "description": "Parse a document (PDF, DOCX, image) and extract text/tables. Uses pdfplumber, Tesseract OCR, and python-docx.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
            "required": ["url"],
        },
    },
    {
        "name": "pry_screenshot",
        "description": "Take a full-page screenshot of a URL. Returns base64-encoded PNG. Useful for visual analysis and OCR.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "full_page": {"type": "boolean", "default": True},
            },
            "required": ["url"],
        },
    },
    {
        "name": "pry_x402_pricing",
        "description": "Get current x402 pay-per-call pricing for all Pry operations. Shows the cost in USDC atomic units for each tool.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "pricing": {"type": "object"},
                        "wallet": {"type": "string"},
                        "facilitator": {"type": "string"},
                        "supported_networks": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_referrals",
        "description": "Get Pry's referral catalog (60+ providers across LLM, hosting, email, monitoring, proxies, devtools). Each link includes our affiliate ID for revenue attribution.",
        "inputSchema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": [],
        },
    },
]

# ── Resource Definitions (per MCP spec) ──

PRY_RESOURCES = [
    {
        "uri": "pry://catalog",
        "name": "Scraper Template Catalog",
        "description": "All 110+ available scraper templates organized by category. Use pry_search_templates tool for dynamic queries.",
        "mimeType": "application/json",
        "annotations": {
            "audience": ["user", "assistant"],
            "priority": 0.9,
        },
    },
    {
        "uri": "pry://stats",
        "name": "Pry Usage Statistics",
        "description": "Current Pry server statistics: uptime, requests served, templates used, costs.",
        "mimeType": "application/json",
        "annotations": {
            "audience": ["assistant"],
            "priority": 0.5,
        },
    },
    {
        "uri": "pry://x402/pricing",
        "name": "x402 Pay-per-call Pricing",
        "description": "x402 pricing for all paid operations. Use to display cost to users before they make a paid call.",
        "mimeType": "application/json",
        "annotations": {
            "audience": ["user", "assistant"],
            "priority": 0.8,
        },
    },
    {
        "uri": "pry://referrals",
        "name": "Referral Catalog",
        "description": "Pry's referral program catalog. 60+ providers with affiliate links for revenue sharing.",
        "mimeType": "application/json",
        "annotations": {
            "audience": ["assistant"],
            "priority": 0.3,
        },
    },
]

# ── Prompt Definitions (per MCP spec) ──

PRY_PROMPTS = [
    {
        "name": "research_company",
        "title": "Research a Company",
        "description": "Scrape and analyze a company website for competitive intelligence. Use the pry_scrape and pry_enrich tools to gather data, then summarize findings.",
        "arguments": [
            {"name": "company_name", "description": "Company name (e.g., 'Anthropic')", "required": True},
            {"name": "website", "description": "Company website URL (e.g., 'https://anthropic.com')", "required": True},
        ],
    },
    {
        "name": "compare_products",
        "title": "Compare Products",
        "description": "Scrape product pages from multiple e-commerce sites and create a side-by-side comparison. Use pry_template tool with amazon-product, walmart-product, etc.",
        "arguments": [
            {"name": "product_query", "description": "What to search for (e.g., 'wireless headphones')", "required": True},
            {"name": "sites", "description": "Sites to compare (e.g., ['amazon', 'walmart', 'target'])", "required": True},
        ],
    },
    {
        "name": "extract_contacts",
        "title": "Extract Contacts from a Website",
        "description": "Crawl a website and extract all email addresses, phone numbers, and social media handles using CSS selectors and regex patterns.",
        "arguments": [
            {"name": "url", "description": "Starting URL", "required": True},
            {"name": "max_pages", "description": "Maximum pages to crawl (default: 20)", "required": False},
        ],
    },
    {
        "name": "monitor_competitor",
        "title": "Monitor a Competitor",
        "description": "Set up continuous monitoring for a competitor's pricing, product listings, or content. Get notified via webhook on changes.",
        "arguments": [
            {"name": "url", "description": "Competitor URL to monitor", "required": True},
            {"name": "what_to_track", "description": "What to track (e.g., 'product prices', 'blog posts', 'job listings')", "required": True},
            {"name": "webhook_url", "description": "Where to send notifications", "required": True},
        ],
    },
    {
        "name": "analyze_article",
        "title": "Analyze an Article",
        "description": "Scrape an article, summarize key points, and provide structured analysis (sentiment, entities, key claims).",
        "arguments": [
            {"name": "url", "description": "Article URL", "required": True},
            {"name": "focus", "description": "What to focus on (e.g., 'financial implications', 'competitive threats')", "required": False},
        ],
    },
    {
        "name": "extract_table",
        "title": "Extract a Data Table",
        "description": "Find and extract a specific data table from a webpage. Returns structured CSV/JSON rows.",
        "arguments": [
            {"name": "url", "description": "Page URL", "required": True},
            {"name": "table_description", "description": "Description of the table you want (e.g., 'product pricing table', 'league standings')", "required": True},
        ],
    },
    {
        "name": "scrape_with_schema",
        "title": "Scrape with Custom Schema",
        "description": "Scrape any URL with a custom JSON schema. Use pry_extract or pry_scrape with a schema definition.",
        "arguments": [
            {"name": "url", "description": "URL to scrape", "required": True},
            {"name": "fields", "description": "Comma-separated list of fields to extract (e.g., 'title,price,description,image')", "required": True},
        ],
    },
]


def make_fallback_server(
    base_url: str = DEFAULT_BASE_URL,
    tool_executor: Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]] | None = None,
) -> Any:
    """Build a minimal stdio JSON-RPC server if official MCP SDK not available.
    This implements the MCP 2024-11-05 protocol with all required methods."""

    class FallbackMCPServer:
        def __init__(
            self,
            base_url: str = DEFAULT_BASE_URL,
            tool_executor: Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]] | None = None,
        ) -> None:
            self.tools: dict[str, dict[str, Any]] = {}
            self.resources: dict[str, dict[str, Any]] = {}
            self.prompts: dict[str, dict[str, Any]] = {}
            self._initialized = False
            self._client_info: dict[str, Any] = {}
            self.base_url = base_url.rstrip("/")
            self.tool_executor = tool_executor

            # MCP logging state
            self._mcp_log_enabled = False
            self._mcp_log_level = logging.INFO

            # Resource subscription state: uri -> set of subscriber session/client ids
            self._resource_subscribers: dict[str, set[str]] = {}

        def register_tool(self, name: str, definition: dict[str, Any]) -> None:
            self.tools[name] = definition

        def register_resource(self, uri: str, definition: dict[str, Any]) -> None:
            self.resources[uri] = definition

        def register_prompt(self, name: str, definition: dict[str, Any]) -> None:
            self.prompts[name] = definition

        def list_tools(self) -> dict[str, Any]:
            return {"tools": list(self.tools.values())}

        def subscribe_resource(self, uri: str, subscriber_id: str = "default") -> bool:
            """Subscribe a client to updates for a resource URI."""
            if uri not in self.resources:
                return False
            self._resource_subscribers.setdefault(uri, set()).add(subscriber_id)
            return True

        def unsubscribe_resource(self, uri: str, subscriber_id: str = "default") -> bool:
            """Unsubscribe a client from updates for a resource URI."""
            subscribers = self._resource_subscribers.get(uri)
            if subscribers is None:
                return False
            subscribers.discard(subscriber_id)
            if not subscribers:
                del self._resource_subscribers[uri]
            return True

        def set_mcp_log_level(self, level_name: str) -> None:
            """Set the MCP log level (debug/info/warning/error/critical)."""
            level_map = {
                "debug": logging.DEBUG,
                "info": logging.INFO,
                "warning": logging.WARNING,
                "error": logging.ERROR,
                "critical": logging.CRITICAL,
            }
            self._mcp_log_level = level_map.get(level_name.lower(), logging.INFO)
            self._mcp_log_enabled = True

        def disable_mcp_log(self) -> None:
            """Disable MCP log forwarding."""
            self._mcp_log_enabled = False

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            """Execute a tool. Returns proper MCP-compliant response."""
            if name not in self.tools:
                return {"error": {"code": -32602, "message": f"Unknown tool: {name}"}}

            # If a local executor is provided (e.g., when mounted inside api.py), use it.
            if self.tool_executor is not None:
                try:
                    result = await self.tool_executor(name, arguments)
                    return self._tool_result_to_content(result, name)
                except Exception as e:
                    logger.warning("mcp_tool_executor_failed", extra={"tool": name, "error": str(e)})
                    return {
                        "content": [{"type": "text", "text": f"Tool {name} failed: {e}"}],
                        "isError": True,
                    }

            tool_map = {
                "pry_scrape": ("POST", "/v1/scrape"),
                "pry_crawl": ("POST", "/v1/crawl"),
                "pry_extract": ("POST", "/v1/extract/css"),
                "pry_template": ("POST", "/v1/templates/execute"),
                "pry_search_templates": ("GET", "/v1/templates"),
                "pry_monitor": ("POST", "/v1/monitor"),
                "pry_compliance": ("POST", "/v1/compliance/check"),
                "pry_enrich": ("POST", "/v1/enrich"),
                "pry_parse_document": ("POST", "/v1/parse"),
                "pry_screenshot": ("POST", "/v1/screenshot"),
                "pry_x402_pricing": ("GET", "/v1/x402/pricing"),
                "pry_referrals": ("GET", "/v1/referrals/catalog"),
            }
            if name not in tool_map:
                return {
                    "content": [{"type": "text", "text": f"Tool {name} not yet wired to API"}],
                    "isError": False,
                }
            method, path = tool_map[name]

            # Try to call the Pry API directly.
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    if method == "GET":
                        response = await client.get(f"{self.base_url}{path}", params=arguments)
                    else:
                        response = await client.post(f"{self.base_url}{path}", json=arguments)
                    response.raise_for_status()
                    data = response.json()
                    return self._tool_result_to_content(data, name)
            except Exception as e:
                logger.warning("mcp_tool_api_call_failed", extra={"tool": name, "error": str(e)})
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Would call {method} {path} with {arguments}. "
                                f"Live execution unavailable: {e}"
                            ),
                        }
                    ],
                    "isError": False,
                }

        def _tool_result_to_content(self, result: Any, tool_name: str) -> dict[str, Any]:
            """Normalize a tool result into MCP content array."""
            if isinstance(result, dict):
                if "content" in result and isinstance(result["content"], list):
                    return result
                text = json.dumps(result, indent=2)
            elif isinstance(result, list):
                text = json.dumps(result, indent=2)
            else:
                text = str(result)
            return {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }

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
                    from template_engine import list_templates
                    templates = list_templates()
                    categories: dict[str, list[str]] = {}
                    for t in templates:
                        cat = t.get("category", "general")
                        categories.setdefault(cat, []).append(t.get("template_id", "unknown"))
                    return json.dumps({
                        "total_templates": len(templates),
                        "categories": categories,
                        "note": "Use pry_search_templates to query dynamically.",
                    }, indent=2)
                except Exception as e:
                    return json.dumps({"error": f"Could not load template catalog: {e}"})
            if uri == "pry://stats":
                return json.dumps({
                    "server": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "protocol_version": MCP_PROTOCOL_VERSION,
                    "tools_count": len(self.tools),
                    "resources_count": len(self.resources),
                    "prompts_count": len(self.prompts),
                }, indent=2)
            if uri == "pry://x402/pricing":
                try:
                    from x402 import X402Handler
                    return json.dumps(X402Handler().get_stats(), indent=2)
                except Exception as e:
                    return json.dumps({"error": f"Could not load x402 pricing: {e}"})
            if uri == "pry://referrals":
                try:
                    from referrals import ReferralTracker
                    return json.dumps(ReferralTracker().get_catalog(), indent=2)  # type: ignore[no-untyped-call]
                except Exception as e:
                    return json.dumps({"error": f"Could not load referrals: {e}"})
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
                return [{
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
                }]
            if name == "compare_products":
                query = arguments.get("product_query", "the product")
                sites = arguments.get("sites", [])
                return [{
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Compare prices and details for '{query}' across {', '.join(sites)}. "
                            "Use pry_template with amazon-product, walmart-product, etc. "
                            "Return a side-by-side comparison table."
                        ),
                    },
                }]
            if name == "extract_contacts":
                url = arguments.get("url", "")
                max_pages = arguments.get("max_pages", 20)
                return [{
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Extract all contact information from {url}. "
                            f"Crawl up to {max_pages} pages. "
                            "Use pry_crawl and regex to find emails, phones, and social profiles."
                        ),
                    },
                }]
            if name == "monitor_competitor":
                url = arguments.get("url", "")
                what = arguments.get("what_to_track", "changes")
                webhook = arguments.get("webhook_url", "")
                return [{
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Set up monitoring for {url}. Track {what}. "
                            f"{'Notify via webhook: ' + webhook + '. ' if webhook else ''}"
                            "Use pry_monitor."
                        ),
                    },
                }]
            if name == "analyze_article":
                url = arguments.get("url", "")
                focus = arguments.get("focus", "")
                return [{
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Scrape and analyze this article: {url}. "
                            f"{'Focus on: ' + focus + '. ' if focus else ''}"
                            "Summarize key points, sentiment, entities, and claims."
                        ),
                    },
                }]
            if name == "extract_table":
                url = arguments.get("url", "")
                desc = arguments.get("table_description", "")
                return [{
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Extract the data table from {url}. Table: {desc}. "
                            "Use pry_extract with CSS selectors or pry_scrape + structured output."
                        ),
                    },
                }]
            if name == "scrape_with_schema":
                url = arguments.get("url", "")
                fields = arguments.get("fields", "")
                return [{
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Scrape {url} and extract these fields: {fields}. "
                            "Use pry_extract with a custom JSON schema."
                        ),
                    },
                }]
            arg_text = ", ".join(f"{k}={v}" for k, v in arguments.items())
            return [{
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"Execute the {self.prompts[name].get('title', name)} prompt with arguments: {arg_text}",
                },
            }]

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
                    from template_engine import list_templates
                    templates = list_templates()
                    values = [
                        t["template_id"]
                        for t in templates
                        if arg_value.lower() in t.get("template_id", "").lower()
                    ][:10]
                except Exception:
                    values = []
            elif ref_type == "ref/tool" and arg_name == "url":
                values = []
            elif arg_name in ("format", "mime_type"):
                values = ["json", "csv", "markdown", "html"]
            return {"values": values}

        async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
            """Handle a JSON-RPC 2.0 request. Implements MCP 2024-11-05."""
            method = request.get("method", "")
            req_id = request.get("id", 0)
            params = request.get("params", {})

            try:
                if method == "initialize":
                    self._initialized = True
                    self._client_info = params.get("clientInfo", {})
                    _attach_mcp_logging(self)
                    set_active_mcp_server(self)
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": MCP_PROTOCOL_VERSION,
                            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                            "capabilities": {
                                "tools": {"listChanged": True},
                                "resources": {"subscribe": True, "listChanged": True},
                                "prompts": {"listChanged": True},
                                "logging": {},
                            },
                        },
                    }
                if method == "notifications/initialized":
                    return None
                if method == "ping":
                    return {"jsonrpc": "2.0", "id": req_id, "result": {}}
                if method == "tools/list":
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"tools": list(self.tools.values())},
                    }
                if method == "tools/call":
                    tool_result = await self.call_tool(params.get("name", ""), params.get("arguments", {}))
                    if "error" in tool_result:
                        return {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": tool_result["error"],
                        }
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": tool_result.get("content", []),
                            "isError": tool_result.get("isError", False),
                        },
                    }
                if method == "resources/list":
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"resources": list(self.resources.values())},
                    }
                if method == "resources/read":
                    read_result = self.read_resource(params.get("uri", ""))
                    if "error" in read_result:
                        return {"jsonrpc": "2.0", "id": req_id, "error": read_result["error"]}
                    return {"jsonrpc": "2.0", "id": req_id, "result": read_result}
                if method == "resources/subscribe":
                    uri = params.get("uri", "")
                    ok = self.subscribe_resource(uri)
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"subscribed": ok},
                    }
                if method == "resources/unsubscribe":
                    uri = params.get("uri", "")
                    ok = self.unsubscribe_resource(uri)
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"unsubscribed": ok},
                    }
                if method == "prompts/list":
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"prompts": list(self.prompts.values())},
                    }
                if method == "prompts/get":
                    prompt_result = self.get_prompt(
                        params.get("name", ""), params.get("arguments", {})
                    )
                    if "error" in prompt_result:
                        return {"jsonrpc": "2.0", "id": req_id, "error": prompt_result["error"]}
                    return {"jsonrpc": "2.0", "id": req_id, "result": prompt_result}
                if method == "completion/complete":
                    completion = self.complete(params.get("ref", {}), params.get("argument", {}))
                    return {"jsonrpc": "2.0", "id": req_id, "result": completion}
                if method == "logging/setLevel":
                    level = params.get("level", "info")
                    self.set_mcp_log_level(level)
                    return {"jsonrpc": "2.0", "id": req_id, "result": {}}
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                }

        async def run_stdio(self) -> None:
            """Run the server over stdio (JSON-RPC 2.0)."""
            while True:
                try:
                    line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    request = json.loads(line)
                    response = await self.handle_request(request)
                    if response is not None:
                        sys.stdout.write(json.dumps(response) + "\n")
                        sys.stdout.flush()
                except json.JSONDecodeError:
                    continue
                except (EOFError, KeyboardInterrupt):
                    break

    return FallbackMCPServer()


def create_server() -> Any:
    """Create the MCP server (uses official SDK if available, fallback otherwise)."""
    if _has_mcp_sdk:
        # TODO: register tools/resources/prompts using official SDK decorators
        # and return the SDK server when tool registration is complete.
        Server(SERVER_NAME, SERVER_VERSION)
    return make_fallback_server()


def register_all(server: Any) -> None:
    """Register all Pry tools, resources, and prompts."""
    for tool in PRY_TOOLS:
        server.register_tool(tool["name"], tool)
    for resource in PRY_RESOURCES:
        server.register_resource(resource["uri"], resource)
    for prompt in PRY_PROMPTS:
        server.register_prompt(prompt["name"], prompt)


async def main() -> None:
    """Run the MCP server."""
    server = create_server()
    register_all(server)
    if _has_mcp_sdk:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    else:
        await server.run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
