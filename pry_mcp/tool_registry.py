"""Pry - MCP tool registry and dict-based dispatch.

``ToolRegistry`` replaces the old 23-deep try/except chain with an iterated
executor chain. The pieces live in:

- ``pry_mcp.tool_cache``     — 10s hot-tool memo (tenant-scoped)
- ``pry_mcp.tool_errors``    — error envelopes + ``ToolNotHandled``
- ``pry_mcp.tool_executors`` — crypto / marketplace / data-domain executors
- ``pry_mcp.tool_standard``  — chain order + the default registry

The public seam (``ToolRegistry``, ``_ToolNotHandled``, ``_hot_tool_cache``,
``combined_tool_executor``) is unchanged; ``combined_tool_executor`` is
resolved lazily because ``tool_standard`` imports this module.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from pry_mcp.tool_cache import _HOT_TOOLS_10S, _hot_tool_cache, hot_cache_get, hot_cache_set
from pry_mcp.tool_errors import ToolNotHandled, _structured_error

logger = logging.getLogger(__name__)

# Names that live in ``tool_standard`` and are re-exported from here. Kept out
# of the module body so ``tool_standard`` can import ``ToolRegistry`` without a
# cycle; ``__getattr__`` (PEP 562) resolves them on first access.
_STANDARD_SEAM = frozenset(
    {"combined_tool_executor", "_default_registry", "register_standard_executors"}
)

# ``combined_tool_executor`` is deliberately absent: it is resolved by
# ``__getattr__`` below, which static analysis cannot see through.
__all__ = [
    "_HOT_TOOLS_10S",
    "_STANDARD_SEAM",
    "ToolNotHandled",
    "ToolRegistry",
    "_ToolNotHandled",
    "_hot_tool_cache",
    "_structured_error",
    "hot_cache_get",
    "hot_cache_set",
]

# Back-compat alias: the sentinel was private before the split.
_ToolNotHandled = ToolNotHandled


class ToolRegistry:
    """Registry of local MCP tool executors with dict-based dispatch.

    Executors are keyed by their dispatcher name (e.g. ``crypto_tool_executor``,
    ``call_legal_tool``) and each is a ``(name, arguments) -> dict | None``
    callable that returns ``None`` (or raises ``ToolNotHandled``) when it does
    not own the tool.
    """

    def __init__(self) -> None:
        self._executors: dict[str, Any] = {}

    def register(self, name: str, executor: Any) -> None:
        """Register an executor under a dispatcher name."""
        self._executors[name] = executor

    async def dispatch(
        self, name: str, arguments: dict[str, Any], identity: str | None = None
    ) -> dict[str, Any]:
        """Dispatch a tool: validate, then run the registered chain in order.

        Raises ``ToolNotHandled`` when no executor owns the tool so callers
        fall through to the REST proxy.
        """
        executor = self._executors.get(name)
        if executor is not None:
            return await executor(name, arguments)

        from pry_mcp.validation import ToolArgError, validate_tool_args

        try:
            validated = validate_tool_args(name, arguments)
        except ToolArgError as exc:
            logger.warning("mcp_tool_invalid_args", extra={"tool": name, "error": str(exc)})
            return _structured_error(name, "invalid_args", str(exc))
        try:
            return await self._combined_tool_executor_inner(name, validated, identity)
        except ToolNotHandled:
            raise
        except Exception as e:  # noqa: BLE001 — protocol boundary: a tool call must never crash the server
            logger.warning("mcp_tool_failed", extra={"tool": name, "error": str(e)})
            return _structured_error(name, "tool_failed", f"Tool {name} failed: {e}")

    async def _combined_tool_executor_inner(
        self, name: str, arguments: dict[str, Any], identity: str | None = None
    ) -> dict[str, Any]:
        """Run every registered executor in order until one owns the tool.

        Hot tools (odds, serp, live_odds, scores, alerts) take the 10s dispatch
        cache path first, so pollers get O(1) reads. Raises ``ToolNotHandled``
        when no dispatcher owns the tool.
        """
        if name in _HOT_TOOLS_10S:
            cached = hot_cache_get(name, arguments, identity)
            if cached is not None:
                logger.debug("mcp_dispatch_cache_hit", extra={"tool": name})
                return cached
        import time

        started = time.monotonic()
        for executor in self._executors.values():
            try:
                result = await executor(name, arguments)
            except ToolNotHandled:
                continue
            if result is not None:
                logger.debug(
                    "mcp_dispatch_ms",
                    extra={"tool": name, "ms": round((time.monotonic() - started) * 1000, 2)},
                )
                if name in _HOT_TOOLS_10S:
                    hot_cache_set(name, arguments, result, identity)
                return result
        raise ToolNotHandled(name)


def __getattr__(name: str) -> Any:
    """Resolve the standard-executor seam on first access (PEP 562).

    ``tool_standard`` imports ``ToolRegistry`` from this module, so importing it
    at module scope would be a cycle. Deferring the import keeps one direction.
    """
    if name in _STANDARD_SEAM:
        from pry_mcp import tool_standard

        return getattr(tool_standard, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
