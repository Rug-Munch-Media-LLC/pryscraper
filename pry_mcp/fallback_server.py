"""Pry - MCP fallback server implementation.

Implements the MCP protocol when the official MCP SDK is not available.
Contains FallbackMCPServer and make_fallback_server().

Split from mcp_production.py.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

import httpx

from pry_mcp.constants import DEFAULT_BASE_URL, MCP_PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION
from pry_mcp.notifications import (
    _attach_mcp_logging,
    set_active_mcp_server,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)


class _ToolNotHandled(Exception):
    """Raised by a local tool executor to fall through to the REST proxy."""


async def _call_crypto_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch crypto-market tools to their guarded handlers in pry_mcp.tools.

    The ``crypto_market`` subpackage is built in parallel by other agents;
    the dispatcher handles missing modules gracefully. Returns ``None`` for
    non-crypto tools so callers fall through to their normal execution path.
    """
    try:
        from pry_mcp.tools import call_crypto_tool
    except ImportError:
        return None
    try:
        return await call_crypto_tool(name, arguments)
    except Exception as e:  # noqa: BLE001 — surface crypto handler failures as MCP errors
        logger.warning("mcp_crypto_tool_failed", extra={"tool": name, "error": str(e)})
        return {
            "content": [{"type": "text", "text": f"Tool {name} failed: {e}"}],
            "isError": True,
        }


async def crypto_tool_executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Local MCP tool executor: runs crypto-market tools directly (guarded
    import) and signals non-crypto tools to fall through to the REST proxy.
    Pass as ``tool_executor`` to ``make_fallback_server``.
    """
    result = await _call_crypto_tool(name, arguments)
    if result is None:
        raise _ToolNotHandled(name)
    return result


async def _call_marketplace_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch marketplace-intelligence tools to their guarded handlers.

    The ``marketplace`` subpackage is built in parallel by other agents; the
    dispatcher handles missing modules gracefully. Returns ``None`` for
    non-marketplace tools so callers fall through to their normal execution path.
    """
    try:
        from pry_mcp.tools import call_marketplace_tool
    except ImportError:
        return None
    try:
        return await call_marketplace_tool(name, arguments)
    except Exception as e:  # noqa: BLE001 — surface marketplace handler failures as MCP errors
        logger.warning("mcp_marketplace_tool_failed", extra={"tool": name, "error": str(e)})
        return {
            "content": [{"type": "text", "text": f"Tool {name} failed: {e}"}],
            "isError": True,
        }


async def marketplace_tool_executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Local MCP tool executor: runs marketplace-intelligence tools directly
    (guarded import) and signals non-marketplace tools to fall through to the
    REST proxy. Pass as ``tool_executor`` to ``make_fallback_server``.
    """
    result = await _call_marketplace_tool(name, arguments)
    if result is None:
        raise _ToolNotHandled(name)
    return result


async def combined_tool_executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Local MCP tool executor chaining the crypto-market then the
    marketplace-intelligence handlers. Raises ``_ToolNotHandled`` when neither
    set handles the tool so callers fall through to the REST proxy.
    """
    try:
        return await crypto_tool_executor(name, arguments)
    except _ToolNotHandled:
        pass
    return await marketplace_tool_executor(name, arguments)


def make_fallback_server(
    base_url: str = DEFAULT_BASE_URL,
    tool_executor: Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
    | None = None,
) -> Any:
    """Build a minimal stdio JSON-RPC server if official MCP SDK not available.
    This implements the MCP 2024-11-05 protocol with all required methods."""

    class FallbackMCPServer:
        def __init__(
            self,
            base_url: str = DEFAULT_BASE_URL,
            tool_executor: Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
            | None = None,
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
                except _ToolNotHandled:
                    # Local executor declined (non-crypto tool) — fall through
                    # to the built-in crypto dispatch / REST proxy below.
                    pass
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "mcp_tool_executor_failed", extra={"tool": name, "error": str(e)}
                    )
                    return {
                        "content": [{"type": "text", "text": f"Tool {name} failed: {e}"}],
                        "isError": True,
                    }

            # Crypto-market tools execute locally via guarded imports
            # (the crypto_market modules land in parallel; degrade to a
            # readable message if a module is absent).
            crypto_result = await _call_crypto_tool(name, arguments)
            if crypto_result is not None:
                return crypto_result

            # Marketplace-intelligence tools execute locally via guarded imports
            # (the marketplace modules land in parallel; degrade to a readable
            # message if a module is absent).
            marketplace_result = await _call_marketplace_tool(name, arguments)
            if marketplace_result is not None:
                return marketplace_result

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
            except (httpx.HTTPError, httpx.RequestError) as e:
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
                    return json.dumps(
                        {
                            "total_templates": len(templates),
                            "categories": categories,
                            "note": "Use pry_search_templates to query dynamically.",
                        },
                        indent=2,
                    )
                except (json.JSONDecodeError, ValueError) as e:
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
                    from x402 import X402Handler

                    return json.dumps(X402Handler().get_stats(), indent=2)
                except (json.JSONDecodeError, ValueError) as e:
                    return json.dumps({"error": f"Could not load x402 pricing: {e}"})
            if uri == "pry://referrals":
                try:
                    from referrals import ReferralTracker

                    return json.dumps(ReferralTracker().get_catalog(), indent=2)  # type: ignore[no-untyped-call]
                except (json.JSONDecodeError, ValueError) as e:
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
            if (
                ref_type == "ref/prompt"
                and ref_name == "extract_contacts"
                and arg_name == "max_pages"
            ):
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
                except Exception:  # noqa: BLE001
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
                    tool_result = await self.call_tool(
                        params.get("name", ""), params.get("arguments", {})
                    )
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
            except Exception as e:  # noqa: BLE001
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
