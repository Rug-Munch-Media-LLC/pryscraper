"""Pry - MCP tool registry and dict-based dispatch.

Holds the hot-cache helpers, the guarded domain dispatchers and the
``combined_tool_executor`` seam; ``ToolRegistry`` replaces the old 23-deep
try/except chain.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)

# Hot tools get a dispatch-level 10s memo (same TTL as the data packages'
# _http_cache). Entries expire lazily on read and the dict is capped at
# _HOT_TOOL_CACHE_MAX (LRU by insertion order).
_HOT_TOOL_CACHE_MAX = 128
_hot_tool_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_HOT_TOOLS_10S = frozenset({"pry_odds", "pry_serp", "pry_live_odds", "pry_scores", "pry_alerts"})
# Argument keys that identify the caller. The 10s memo must never let one
# tenant's paid response be served to another on identical arguments.
_IDENTITY_KEYS = ("api_key", "apikey", "tenant", "tenant_id", "auth", "caller_id")


def _identity_of(arguments: dict[str, Any], identity: str | None = None) -> str:
    """Caller namespace for the hot cache: explicit, else an argument, else public."""
    if identity:
        return str(identity)
    for name in _IDENTITY_KEYS:
        value = arguments.get(name)
        if value:
            return str(value)
    return "public"


def _hot_cache_get(
    name: str, arguments: dict[str, Any], identity: str | None = None
) -> dict[str, Any] | None:
    """Return a fresh (<=10s) cached MCP result for a hot tool, else None."""
    import time

    key = (
        name,
        _identity_of(arguments, identity),
        json.dumps(arguments, sort_keys=True, default=str),
    )
    entry = _hot_tool_cache.get(key)
    if entry is None:
        return None
    cached_at, result = entry
    if time.monotonic() - cached_at < 10.0:
        return result
    _hot_tool_cache.pop(key, None)
    return None


def _hot_cache_set(
    name: str, arguments: dict[str, Any], result: dict[str, Any], identity: str | None = None
) -> None:
    """Memoize an MCP result for a hot tool for 10 seconds (bounded LRU)."""
    import time

    if len(_hot_tool_cache) >= _HOT_TOOL_CACHE_MAX:
        # Drop the oldest entry (dicts preserve insertion order).
        _hot_tool_cache.pop(next(iter(_hot_tool_cache)))
    key = (
        name,
        _identity_of(arguments, identity),
        json.dumps(arguments, sort_keys=True, default=str),
    )
    _hot_tool_cache[key] = (time.monotonic(), result)


class _ToolNotHandled(Exception):
    """Raised by a local tool executor to fall through to the REST proxy."""


async def _call_crypto_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch crypto tools; ``None`` means "not mine, fall through"."""
    try:
        from pry_mcp.tools import call_crypto_tool
    except ImportError as e:
        logger.warning(
            "suppressed %s in _call_crypto_tool (tool_registry.py:77): %s",
            "ImportError",
            e,
        )
        return None
    try:
        return await call_crypto_tool(name, arguments)
    except Exception as e:  # noqa: BLE001 — surface crypto handler failures as MCP errors
        logger.warning("mcp_crypto_tool_failed", extra={"tool": name, "error": str(e)})
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"error": f"Tool {name} failed: {e}", "code": "TOOL_EXECUTION_FAILED"}
                    ),
                }
            ],
            "isError": True,
        }


async def crypto_tool_executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run crypto tools locally; raise ``_ToolNotHandled`` to fall through."""
    result = await _call_crypto_tool(name, arguments)
    if result is None:
        raise _ToolNotHandled(name)
    return result


async def _call_marketplace_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch marketplace tools; ``None`` means "not mine, fall through"."""
    try:
        from pry_mcp.tools import call_marketplace_tool
    except ImportError as e:
        logger.warning(
            "suppressed %s in _call_marketplace_tool (tool_registry.py:116): %s",
            "ImportError",
            e,
        )
        return None
    try:
        return await call_marketplace_tool(name, arguments)
    except Exception as e:  # noqa: BLE001 — surface marketplace handler failures as MCP errors
        logger.warning("mcp_marketplace_tool_failed", extra={"tool": name, "error": str(e)})
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"error": f"Tool {name} failed: {e}", "code": "TOOL_EXECUTION_FAILED"}
                    ),
                }
            ],
            "isError": True,
        }


async def marketplace_tool_executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run marketplace tools locally; raise ``_ToolNotHandled`` to fall through."""
    result = await _call_marketplace_tool(name, arguments)
    if result is None:
        raise _ToolNotHandled(name)
    return result


async def _call_domain_tool(
    dispatcher_name: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """Call one guarded domain dispatcher; ``None`` means "not mine" (lazy import)."""
    try:
        from pry_mcp import tools as _mcp_tools
    except ImportError as e:
        logger.warning(
            "suppressed %s in _call_domain_tool (tool_registry.py:157): %s",
            "ImportError",
            e,
        )
        return None
    dispatcher = getattr(_mcp_tools, dispatcher_name, None)
    if dispatcher is None:
        return None
    try:
        return await dispatcher(name, arguments)
    except Exception as e:  # noqa: BLE001 — surface handler failures as MCP errors
        logger.warning("mcp_domain_tool_failed", extra={"tool": name, "error": str(e)})
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"error": f"Tool {name} failed: {e}", "code": "TOOL_EXECUTION_FAILED"}
                    ),
                }
            ],
            "isError": True,
        }


def _structured_error(tool_name: str, code: str, message: str) -> dict[str, Any]:
    """Error result for both transports: ``error`` + MCP ``content``/``isError``."""
    return {
        "error": {"code": code, "message": message},
        "content": [{"type": "text", "text": json.dumps({"error": message, "code": code})}],
        "isError": True,
    }


def _domain_executor(
    dispatcher_name: str,
) -> Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any] | None]]:
    """Build a ``(name, arguments)`` executor that calls one domain dispatcher."""

    async def executor(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        return await _call_domain_tool(dispatcher_name, name, arguments)

    return executor


# The data-domain dispatchers chained after crypto/marketplace, in dispatch
# order (actor-parity first, then the twenty-one data-domain packages).
_DOMAIN_DISPATCHERS = (
    "call_mega_search_tool",
    "call_legal_tool",
    "call_realestate_tool",
    "call_jobs_tool",
    "call_travel_tool",
    "call_attention_tool",
    "call_local_tool",
    "call_gov_tool",
    "call_ip_tool",
    "call_sports_tool",
    "call_climate_tool",
    "call_research_tool",
    "call_events_tool",
    "call_freight_tool",
    "call_energy_tool",
    "call_food_tool",
    "call_supply_tool",
    "call_app_store_tool",
    "call_news_tool",
    "call_compliance_tool",
    "call_deals_tool",
    "call_bidding_tool",
)


class ToolRegistry:
    """Registry of local MCP tool executors with dict-based dispatch.

    Replaces the old 23-deep try/except chain in ``_combined_tool_executor_inner``
    with iteration over registered executors. Executors are keyed by their
    dispatcher name (e.g. ``crypto_tool_executor``, ``call_legal_tool``) and
    each is a ``(name, arguments) -> dict | None`` callable that returns
    ``None`` (or raises ``_ToolNotHandled``) when it does not own the tool.
    """

    def __init__(self) -> None:
        self._executors: dict[str, Callable] = {}

    def register(self, name: str, executor: Callable) -> None:
        """Register an executor under a dispatcher name."""
        self._executors[name] = executor

    async def dispatch(
        self, name: str, arguments: dict[str, Any], identity: str | None = None
    ) -> dict[str, Any]:
        """Dispatch a tool to a registered executor.

        Looks up ``name`` directly in ``self._executors``; if a tool-name-keyed
        executor is registered it is called directly. Otherwise the full chain
        of registered executors runs (validated seam). Raises ``_ToolNotHandled``
        when no executor owns the tool so callers fall through to the REST proxy.
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
        except _ToolNotHandled:
            raise
        except Exception as e:  # noqa: BLE001 — structured error, not a crash
            logger.warning("mcp_tool_failed", extra={"tool": name, "error": str(e)})
            return _structured_error(name, "tool_failed", f"Tool {name} failed: {e}")

    async def _combined_tool_executor_inner(
        self, name: str, arguments: dict[str, Any], identity: str | None = None
    ) -> dict[str, Any]:
        """Run every registered executor in order until one owns the tool.

        Order: actor-parity, crypto-market, marketplace-intelligence, then the
        twenty-one data-domain dispatchers (legal, real estate, jobs, travel,
        attention, local, gov, ip, sports, climate, research, events, freight,
        energy, food, supply, app-store, news, compliance, deals, bidding).
        Raises ``_ToolNotHandled`` when no dispatcher owns the tool so callers
        fall through to the REST proxy.

        Hot tools (odds, serp, live_odds, scores, alerts) take the 10s dispatch
        cache path before the guarded-import chain runs, so pollers get O(1)
        reads. Every dispatch logs its wall time at debug level.
        """
        if name in _HOT_TOOLS_10S:
            cached = _hot_cache_get(name, arguments, identity)
            if cached is not None:
                logger.debug("mcp_dispatch_cache_hit", extra={"tool": name})
                return cached
        import time

        started = time.monotonic()
        for executor in self._executors.values():
            try:
                result = await executor(name, arguments)
            except _ToolNotHandled as e:
                logger.warning(
                    "suppressed %s in _combined_tool_executor_inner (tool_registry.py:302): %s",
                    "_ToolNotHandled",
                    e,
                )
                continue
            if result is not None:
                logger.debug(
                    "mcp_dispatch_ms",
                    extra={"tool": name, "ms": round((time.monotonic() - started) * 1000, 2)},
                )
                if name in _HOT_TOOLS_10S:
                    _hot_cache_set(name, arguments, result, identity)
                return result
        raise _ToolNotHandled(name)


def register_standard_executors(registry: ToolRegistry) -> ToolRegistry:
    """Register the standard local executor chain on ``registry`` (in order)."""
    registry.register("call_actor_tool", _domain_executor("call_actor_tool"))
    registry.register("crypto_tool_executor", crypto_tool_executor)
    registry.register("marketplace_tool_executor", marketplace_tool_executor)
    for dispatcher_name in _DOMAIN_DISPATCHERS:
        registry.register(dispatcher_name, _domain_executor(dispatcher_name))
    return registry


# Module-level default registry used by the standalone ``combined_tool_executor``
# seam (kept for backward compatibility with callers that pass it as the
# ``tool_executor`` to ``make_fallback_server``).
_default_registry = register_standard_executors(ToolRegistry())


async def combined_tool_executor(
    name: str, arguments: dict[str, Any], identity: str | None = None
) -> dict[str, Any]:
    """Validated seam in front of the chained domain dispatchers.

    Validates arguments against ``pry_mcp.validation.TOOL_REQUIREMENTS``
    (top-20 high-risk tools) and converts validation/execution failures into
    structured error dicts instead of propagating. ``_ToolNotHandled`` still
    propagates so callers fall through to the REST proxy.
    """
    return await _default_registry.dispatch(name, arguments, identity)
