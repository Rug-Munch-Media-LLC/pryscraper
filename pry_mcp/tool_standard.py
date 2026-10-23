"""Pry - the standard MCP executor chain.

Owns dispatch ORDER (actor parity, crypto, marketplace, then the twenty-two
data-domain dispatchers) and the module-level default registry behind
``combined_tool_executor``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pry_mcp.tool_executors import (
    crypto_tool_executor,
    domain_executor,
    marketplace_tool_executor,
)

if TYPE_CHECKING:
    from pry_mcp.tool_registry import ToolRegistry

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


def register_standard_executors(registry: ToolRegistry) -> ToolRegistry:
    """Register the standard local executor chain on ``registry`` (in order)."""
    registry.register("call_actor_tool", domain_executor("call_actor_tool"))
    registry.register("crypto_tool_executor", crypto_tool_executor)
    registry.register("marketplace_tool_executor", marketplace_tool_executor)
    for dispatcher_name in _DOMAIN_DISPATCHERS:
        registry.register(dispatcher_name, domain_executor(dispatcher_name))
    return registry


def _build_default_registry() -> ToolRegistry:
    """Build the module-level registry.

    ``ToolRegistry`` is imported here rather than at module scope because
    ``tool_registry`` re-exports this module's public seam; the local import
    keeps the dependency one-way.
    """
    from pry_mcp.tool_registry import ToolRegistry

    return register_standard_executors(ToolRegistry())


_default_registry = _build_default_registry()


async def combined_tool_executor(
    name: str, arguments: dict[str, Any], identity: str | None = None
) -> dict[str, Any]:
    """Validated seam in front of the chained domain dispatchers.

    Validates arguments against ``pry_mcp.validation.TOOL_REQUIREMENTS``
    (top-20 high-risk tools) and converts validation/execution failures into
    structured error dicts instead of propagating. ``ToolNotHandled`` still
    propagates so callers fall through to the REST proxy.
    """
    return await _default_registry.dispatch(name, arguments, identity)
