"""Pry - MCP local dispatcher executors (crypto, marketplace, data domains).

Every executor has the same contract: return the tool result when it owns the
tool, return ``None`` when it does not. ``tool_standard`` chains them and the
registry falls through to the REST proxy when nothing owns the call.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pry_mcp.tool_errors import HANDLER_ERRORS, ToolNotHandled, handler_failure

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)


def _resolve_dispatcher(attr_name: str) -> Any:
    """Import one dispatcher from ``pry_mcp.tools``; ``None`` when it is absent."""
    try:
        from pry_mcp import tools as mcp_tools
    except ImportError as e:
        logger.warning(
            "mcp_tools_package_unavailable",
            extra={"dispatcher": attr_name, "error": str(e)},
        )
        return None
    return getattr(mcp_tools, attr_name, None)


async def _run_dispatcher(
    attr_name: str, failure_event: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """Call one dispatcher; ``None`` when absent, error envelope when it raises."""
    dispatcher = _resolve_dispatcher(attr_name)
    if dispatcher is None:
        return None
    try:
        return await dispatcher(name, arguments)
    except HANDLER_ERRORS as e:
        logger.warning(failure_event, extra={"tool": name, "error": str(e)})
        return handler_failure(name, e)


async def _call_crypto_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch crypto tools; ``None`` means "not mine, fall through"."""
    return await _run_dispatcher("call_crypto_tool", "mcp_crypto_tool_failed", name, arguments)


async def crypto_tool_executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run crypto tools locally; raise ``ToolNotHandled`` to fall through."""
    result = await _call_crypto_tool(name, arguments)
    if result is None:
        raise ToolNotHandled(name)
    return result


async def _call_marketplace_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch marketplace tools; ``None`` means "not mine, fall through"."""
    return await _run_dispatcher(
        "call_marketplace_tool", "mcp_marketplace_tool_failed", name, arguments
    )


async def marketplace_tool_executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run marketplace tools locally; raise ``ToolNotHandled`` to fall through."""
    result = await _call_marketplace_tool(name, arguments)
    if result is None:
        raise ToolNotHandled(name)
    return result


async def _call_domain_tool(
    dispatcher_name: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """Call one guarded data-domain dispatcher; ``None`` means "not mine"."""
    return await _run_dispatcher(dispatcher_name, "mcp_domain_tool_failed", name, arguments)


def domain_executor(
    dispatcher_name: str,
) -> Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any] | None]]:
    """Build a ``(name, arguments)`` executor that calls one domain dispatcher."""

    async def executor(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        return await _call_domain_tool(dispatcher_name, name, arguments)

    return executor
