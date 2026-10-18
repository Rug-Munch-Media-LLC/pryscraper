"""MCP SDK server construction (split from sdk_server)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pry_mcp.constants import SERVER_NAME, SERVER_VERSION

if TYPE_CHECKING:
    from mcp.types import Tool

logger = logging.getLogger(__name__)


def build_sdk_server() -> Any:
    # Resolved lazily: these live in modules that import this one at startup.

    from pry_mcp.fallback_factory import make_fallback_server
    from pry_mcp.sdk_server import register_all
    from pry_mcp.tool_registry import combined_tool_executor

    """Build an official MCP SDK server exposing every Pry tool/resource/prompt.

    The SDK handlers delegate execution to the same guarded dispatch + REST
    proxy chain as the fallback server (``combined_tool_executor``), so the
    stdio transport behaves identically to the HTTP transports.

    Only called when the official ``mcp`` SDK is importable; the SDK imports
    are deliberately local so this module still imports cleanly when the SDK
    is not installed (the fallback server path).
    """
    from mcp.server import Server

    # Kept runtime-importable: SDK <2 may resolve handler annotations.

    # The fallback server holds the execution logic (local executors,
    # domain dispatch, REST proxy fallback); the SDK server wraps it.
    delegate = make_fallback_server(tool_executor=combined_tool_executor)
    register_all(delegate)

    server = Server(SERVER_NAME, version=SERVER_VERSION)
    # MCP SDK >=2.0 removed the decorator-based low-level Server API
    # (list_tools/call_tool/...). Detect it early and let create_server()
    # fall back to the built-in server, which exposes the identical
    # tool/resource/prompt surface over stdio.
    if not hasattr(server, "list_tools"):
        raise AttributeError(
            "MCP SDK >=2.0 detected: decorator Server API removed; "
            "using Pry fallback server instead"
        )
    # The decorator attributes only exist on SDK <2; the hasattr guard above
    # proves they exist at runtime, and the Any cast keeps mypy happy.
    return _wire_legacy(server, delegate)


def _wire_legacy(server: Any, delegate: Any) -> Any:
    """Attach the legacy decorator handlers; SDK >=2 already raised above."""
    from mcp.types import (
        TextContent,
        Tool,
    )

    from pry_mcp.tool_registry import PRY_TOOLS

    legacy: Any = server
    dec_list_tools = legacy.list_tools
    dec_call_tool = legacy.call_tool
    # Marker so ``register_all`` (and callers) know the SDK server already
    # carries its registrations via handlers.
    server._pry_sdk_registered = True  # type: ignore[attr-defined]

    @dec_list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=tool["name"],
                description=tool.get("description", ""),
                inputSchema=tool.get("inputSchema", {"type": "object", "properties": {}}),
                annotations=tool.get("annotations"),
            )
            for tool in PRY_TOOLS
        ]

    @dec_call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result = await delegate.call_tool(name, arguments or {})
        if "error" in result:
            raise ValueError(str(result["error"].get("message", f"Unknown tool: {name}")))
        blocks: list[TextContent] = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                blocks.append(TextContent(type="text", text=item.get("text", "")))
        if not blocks:
            blocks.append(TextContent(type="text", text=""))
        return blocks

    return _wire_assets(server, delegate, legacy)


def _wire_assets(server: Any, delegate: Any, legacy: Any) -> Any:
    """Resources and prompts handlers (kept apart from the tool handlers)."""
    from mcp.types import (
        AnyUrl,
        ReadResourceResult,
        Resource,
        TextResourceContents,
    )

    from pry_mcp.resources_handler import PRY_RESOURCES
    dec_list_resources = legacy.list_resources
    dec_read_resource = legacy.read_resource


    @dec_list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(
                uri=str(r["uri"]),
                name=r["name"],
                description=r.get("description", ""),
                mimeType=r.get("mimeType", "text/plain"),
            )
            for r in PRY_RESOURCES
        ]

    @dec_read_resource()
    async def read_resource(uri: AnyUrl) -> ReadResourceResult:
        uri_str = str(uri)
        if uri_str not in delegate.resources:
            raise ValueError(f"Resource not found: {uri_str}")
        return ReadResourceResult(
            contents=[
                TextResourceContents(
                    uri=uri_str,
                    mime_type=delegate.resources[uri_str].get("mimeType", "text/plain"),
                    text=delegate._resource_text(uri_str),
                )
            ]
        )

    return _wire_prompts(server, delegate, legacy)


def _wire_prompts(server: Any, delegate: Any, legacy: Any) -> Any:
    """Prompt handlers (resources are wired by ``_wire_assets``)."""
    from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent

    from pry_mcp.prompts import PRY_PROMPTS

    dec_list_prompts = legacy.list_prompts
    dec_get_prompt = legacy.get_prompt

    @dec_list_prompts()
    async def list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name=p["name"],
                description=p.get("description", ""),
                arguments=[
                    PromptArgument(
                        name=a["name"],
                        description=a.get("description", ""),
                        required=a.get("required", False),
                    )
                    for a in p.get("arguments", [])
                ],
            )
            for p in PRY_PROMPTS
        ]

    @dec_get_prompt()
    async def get_prompt(name: str, arguments: dict[str, Any]) -> GetPromptResult:
        if name not in delegate.prompts:
            raise ValueError(f"Prompt not found: {name}")
        messages = delegate._prompt_messages(name, arguments or {})
        return GetPromptResult(
            description=delegate.prompts[name].get("description", ""),
            messages=[
                PromptMessage(
                    # mcp SDK >=2: Role is Literal["user", "assistant"], not an enum.
                    role="user" if m.get("role") == "user" else "assistant",
                    content=TextContent(type="text", text=m.get("content", {}).get("text", "")),
                )
                for m in messages
            ],
        )

    return server


