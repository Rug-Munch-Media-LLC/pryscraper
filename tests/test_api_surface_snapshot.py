"""Snapshot tests for the public MCP and x402 API surfaces.

These tests guard against accidental breakage when refactoring
mcp_production.py and x402.py into sub-packages.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations


class TestMCPPublicSurface:
    """The mcp_production shim must expose the same public API as before."""

    def test_required_symbols_exist(self) -> None:
        import mcp_production

        required = {
            "DEFAULT_BASE_URL",
            "MCP_PROTOCOL_VERSION",
            "SERVER_NAME",
            "SERVER_VERSION",
            "MCPLoggingHandler",
            "PRY_PROMPTS",
            "PRY_RESOURCES",
            "PRY_TOOLS",
            "create_server",
            "main",
            "make_fallback_server",
            "notify_resource_changed",
            "notify_resource_list_changed",
            "notify_tool_list_changed",
            "register_all",
            "register_mcp_notification_observer",
            "set_active_mcp_server",
            "unregister_mcp_notification_observer",
        }
        missing = {name for name in required if not hasattr(mcp_production, name)}
        assert not missing, f"Missing public MCP symbols: {missing}"

    def test_tool_definitions_are_non_empty(self) -> None:
        import mcp_production

        assert isinstance(mcp_production.PRY_TOOLS, list)
        assert len(mcp_production.PRY_TOOLS) > 0
        assert isinstance(mcp_production.PRY_RESOURCES, list)
        assert isinstance(mcp_production.PRY_PROMPTS, list)


class TestX402PublicSurface:
    """The x402 shim must expose the same public API as before."""

    def test_required_symbols_exist(self) -> None:
        import x402

        required = {
            "X402Asset",
            "X402Handler",
            "X402Network",
            "X402Scheme",
            "FacilitatorConfig",
            "FacilitatorRouter",
            "build_payment_required",
            "create_batch_payment",
            "create_payment_request",
            "get_facilitator_router",
            "is_batch_paid",
            "require_payment_legacy",
            "set_facilitator_router",
            "verify_batch_payment",
        }
        missing = {name for name in required if not hasattr(x402, name)}
        assert not missing, f"Missing public x402 symbols: {missing}"

    def test_enum_values_consistent(self) -> None:
        import x402

        assert x402.X402Scheme.EXACT.value == "exact"
        assert x402.X402Network.ETHEREUM.value == "ethereum"
        assert x402.X402Asset.USDC.value == "USDC"
