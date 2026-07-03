# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for x402 and MCP spec compliance."""

import asyncio
import base64
import json
from typing import Any

from pry_mcp import (
    MCP_PROTOCOL_VERSION,
    PRY_PROMPTS,
    PRY_RESOURCES,
    PRY_TOOLS,
    make_fallback_server,
    register_all,
)
from x402 import (
    X402_PRICING,
    FacilitatorRouter,
    X402Asset,
    X402Handler,
    X402Network,
    X402Scheme,
    _decode_payment_signature,
    _encode_payment_required_body,
    build_payment_required,
    set_facilitator_router,
)


class _AlwaysVerifyRouter(FacilitatorRouter):
    """Test router that always verifies payments without network calls."""

    def __init__(self) -> None:
        super().__init__(facilitators=[])

    async def verify(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        return {"verified": True, "reason": "", "settlement": None, "facilitator": "test"}

    async def settle(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "transaction": tx_hash,
            "network": network,
            "payment_id": payment_id,
            "facilitator": "test",
            "settled_at": "2026-01-01T00:00:00+00:00",
        }


# ── MCP spec compliance ──


def test_mcp_protocol_version() -> None:
    """MCP 2024-11-05 is the current spec version."""
    assert MCP_PROTOCOL_VERSION == "2024-11-05"


def test_tools_have_input_schema() -> None:
    """Every tool must have a JSON schema for inputs."""
    for tool in PRY_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema


def test_tools_have_output_schema() -> None:
    """Best practice: tools should declare output schemas."""
    tools_with_output = [t for t in PRY_TOOLS if "outputSchema" in t]
    assert len(tools_with_output) >= 3


def test_resources_have_required_fields() -> None:
    for r in PRY_RESOURCES:
        assert "uri" in r
        assert "name" in r
        assert "description" in r
        assert "mimeType" in r


def test_prompts_have_required_fields() -> None:
    for p in PRY_PROMPTS:
        assert "name" in p
        assert "description" in p
        assert "arguments" in p
        for arg in p["arguments"]:
            assert "name" in arg
            assert "description" in arg
            assert "required" in arg


def test_initialize_response() -> None:
    """Test that initialize returns proper protocol version and capabilities."""
    server = make_fallback_server()
    response = asyncio.run(
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "test", "version": "1.0"}},
            }
        )
    )
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert "tools" in response["result"]["capabilities"]
    assert "resources" in response["result"]["capabilities"]
    assert "prompts" in response["result"]["capabilities"]


def test_tools_list() -> None:
    server = make_fallback_server()
    register_all(server)
    response = asyncio.run(
        server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    )
    assert "tools" in response["result"]
    assert len(response["result"]["tools"]) >= 10


def test_tool_call_returns_content_array() -> None:
    """tools/call must return content array per MCP spec."""
    server = make_fallback_server()
    register_all(server)
    response = asyncio.run(
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "pry_x402_pricing", "arguments": {}},
            }
        )
    )
    assert "content" in response["result"]
    assert isinstance(response["result"]["content"], list)
    assert "isError" in response["result"]


def test_resources_list() -> None:
    server = make_fallback_server()
    register_all(server)
    response = asyncio.run(
        server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    )
    assert "resources" in response["result"]
    assert len(response["result"]["resources"]) >= 3


def test_resource_read_returns_contents() -> None:
    server = make_fallback_server()
    register_all(server)
    response = asyncio.run(
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {"uri": "pry://stats"},
            }
        )
    )
    assert "contents" in response["result"]


def test_prompts_list() -> None:
    server = make_fallback_server()
    register_all(server)
    response = asyncio.run(
        server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})
    )
    assert "prompts" in response["result"]
    assert len(response["result"]["prompts"]) >= 5


def test_prompt_get_returns_messages() -> None:
    server = make_fallback_server()
    register_all(server)
    response = asyncio.run(
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "prompts/get",
                "params": {"name": "research_company", "arguments": {"company_name": "Anthropic"}},
            }
        )
    )
    assert "messages" in response["result"]
    assert len(response["result"]["messages"]) > 0


def test_ping() -> None:
    server = make_fallback_server()
    response = asyncio.run(server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
    assert response["result"] == {}


def test_unknown_method_error() -> None:
    server = make_fallback_server()
    response = asyncio.run(
        server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "unknown_method"})
    )
    assert "error" in response
    assert response["error"]["code"] == -32601


# ── x402 spec compliance ──


def test_x402_atomic_units() -> None:
    """Prices must be in atomic units (6 decimals for USDC)."""
    for op, info in X402_PRICING.items():
        amount_atomic = int(info["price_usd"] * 1_000_000)
        assert amount_atomic > 0, f"Operation {op} has zero price"


def test_x402_accepts_array_format() -> None:
    """PaymentRequired must have accepts array per x402 spec."""
    body = build_payment_required("scrape", "https://pry.dev/api/scrape")
    assert body["x402Version"] == 1
    assert "accepts" in body
    assert isinstance(body["accepts"], list)
    assert len(body["accepts"]) >= 1


def test_x402_acceptance_has_required_fields() -> None:
    """Each acceptance option must have required fields per x402 spec."""
    body = build_payment_required("scrape")
    for acceptance in body["accepts"]:
        assert "scheme" in acceptance
        assert "network" in acceptance
        assert "maxAmountRequired" in acceptance
        assert "resource" in acceptance
        assert "payToAddress" in acceptance
        assert "asset" in acceptance


def test_x402_base64_encoding() -> None:
    """PAYMENT-REQUIRED header must be Base64-encoded JSON."""
    body = build_payment_required("scrape")
    encoded = _encode_payment_required_body(body)
    decoded = base64.b64decode(encoded).decode()
    parsed = json.loads(decoded)
    assert parsed == body


def test_x402_signature_decoding() -> None:
    """PAYMENT-SIGNATURE header must be Base64-encoded JSON."""
    test_payload = {"scheme": "exact", "network": "base", "payload": "0x1234"}
    encoded = base64.b64encode(json.dumps(test_payload).encode()).decode()
    decoded = _decode_payment_signature(encoded)
    assert decoded == test_payload


def test_x402_handler_create_payment_required() -> None:
    handler = X402Handler()
    body, headers = handler.create_payment_required("scrape", "https://pry.dev/api/scrape")
    assert body["x402Version"] == 1
    assert "PAYMENT-REQUIRED" in headers
    decoded = json.loads(base64.b64decode(headers["PAYMENT-REQUIRED"]).decode())
    assert decoded == body


def test_x402_handler_require_payment() -> None:
    handler = X402Handler()
    response = handler.require_payment("crawl")
    assert response["status_code"] == 402
    assert "PAYMENT-REQUIRED" in response["headers"]
    assert "accepts" in response["body"]


def test_x402_handler_verify_and_settle() -> None:
    set_facilitator_router(_AlwaysVerifyRouter())
    try:
        handler = X402Handler()
        payment_id = "test-pay-123"
        tx_hash = "0xabc123"
        verify_result = asyncio.run(handler.verify_payment(payment_id, tx_hash))
        assert verify_result["verified"] is True
        assert handler.is_paid(payment_id) is True
        settlement = asyncio.run(handler.settle_payment(payment_id, tx_hash))
        assert settlement["success"] is True
        assert settlement["transaction"] == tx_hash
    finally:
        set_facilitator_router(FacilitatorRouter())


def test_x402_multi_chain_support() -> None:
    """x402 should support multiple chains."""
    body = build_payment_required("scrape")
    networks = {a["network"] for a in body["accepts"]}
    assert "base" in networks
    assert "solana" in networks


def test_x402_scheme_enum() -> None:
    assert X402Scheme.EXACT.value == "exact"
    assert X402Scheme.UPTO.value == "upto"


def test_x402_network_enum() -> None:
    assert X402Network.BASE.value == "base"
    assert X402Network.SOLANA.value == "solana"
    assert X402Network.ETHEREUM.value == "ethereum"


def test_x402_asset_enum() -> None:
    assert X402Asset.USDC.value == "USDC"
    assert X402Asset.USDT.value == "USDT"
    assert X402Asset.ETH.value == "ETH"


def test_x402_stats_includes_standards() -> None:
    handler = X402Handler()
    stats = handler.get_stats()
    assert "wallet" in stats
    assert "facilitator" in stats
    assert "pricing" in stats
    assert "supported_networks" in stats
    assert "supported_assets" in stats
    assert "supported_schemes" in stats
    assert "base" in stats["supported_networks"]
    assert "solana" in stats["supported_networks"]
