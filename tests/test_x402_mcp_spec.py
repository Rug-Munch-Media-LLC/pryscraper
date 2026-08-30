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

from pry.payments.x402 import (
    CAIP2_NETWORK_IDS,
    SUPPORTED_ASSETS,
    SUPPORTED_NETWORKS,
    X402_ASSET_USD_PER_UNIT,
    X402_PRICING,
    FacilitatorRouter,
    X402Asset,
    X402Handler,
    X402Network,
    X402Scheme,
    _decode_payment_signature,
    _encode_payment_required_body,
    asset_to_atomic,
    build_multi_asset_accepts,
    build_payment_required,
    is_asset_supported,
    normalize_network_id,
    resolve_asset_entry,
    resolve_price_usd,
    set_facilitator_router,
    validate_client_amount,
)
from pry_mcp import (
    MCP_PROTOCOL_VERSION,
    PRY_PROMPTS,
    PRY_RESOURCES,
    PRY_TOOLS,
    make_fallback_server,
    register_all,
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


class _AlwaysVerifySettleFail(FacilitatorRouter):
    """Test router whose verify always passes but whose settle always FAILS.

    Used to prove settlement-success gating (fix #3): a verify that passes but
    a settle that fails must NOT grant access — the gate responds 402.
    """

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
        return {"success": False, "reason": "settlement rejected", "transaction": tx_hash}


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


def test_x402_handler_verify_and_settle(tmp_path) -> None:
    """Verify may pass but a FAILED settle must deny access (fix #3).

    The enforcement middleware owns the decision: it calls verify then settle
    and only grants a 2xx when settlement succeeds. Driving the REAL middleware
    with a router that always verifies but always fails settlement must return a
    402 payment-required challenge — never a 2xx. Replay-dedup (single-use
    tx_hash) is asserted too.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pry.payments.x402_middleware import X402Middleware

    app = FastAPI()

    @app.get("/v1/scrape")
    async def scrape():
        return {"ok": True}

    set_facilitator_router(_AlwaysVerifySettleFail())
    try:
        handler = X402Handler(
            payments_file=tmp_path / "payments.jsonl",
            settlements_file=tmp_path / "settlements.jsonl",
        )
        mw = X402Middleware(app=app)
        mw.handler = handler  # isolate audit logs to this test

        client = TestClient(mw, raise_server_exceptions=False)
        sig = base64.b64encode(
            json.dumps(
                {
                    "payment_id": "test-pay-123",
                    "tx_hash": "0xabc123",
                    "network": "base",
                    "asset": "USDC",
                    "amount_usd": 1.0,
                }
            ).encode()
        ).decode()

        # Access denied when settlement FAILS: verify passes (router.verify=True)
        # but settle returns success=False, so the gate responds 402 — no 2xx.
        r = client.get("/v1/scrape", headers={"PAYMENT-SIGNATURE": sig})
        assert r.status_code == 402
        assert "PAYMENT-REQUIRED" in r.headers

        # Replay-dedup: a fresh tx_hash verifies once, then is single-use.
        verify_once = asyncio.run(handler.verify_payment("test-pay-r1", "0xreplay1"))
        assert verify_once["verified"] is True
        replay = asyncio.run(handler.verify_payment("test-pay-r2", "0xreplay1"))
        assert replay["verified"] is False
        assert replay["reason"] == "tx_hash already consumed"
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


# ── Multi-asset / multi-chain acceptance (CAIP-2) ──


def test_supported_assets_covers_business_networks() -> None:
    """The canonical table must cover the 7 CAIP-2 networks the business wants."""
    assert set(SUPPORTED_ASSETS.keys()) == {
        "eip155:8453",  # Base
        "eip155:1",  # Ethereum
        "eip155:42161",  # Arbitrum
        "eip155:10",  # Optimism
        "eip155:137",  # Polygon
        "solana:mainnet",
        "tron:mainnet",
    }
    assert len(SUPPORTED_NETWORKS) > 0  # non-empty metadata list
    assert len(SUPPORTED_NETWORKS) == 7


def test_supported_assets_known_addresses() -> None:
    """The known token addresses from the acceptance criteria are canonical."""
    assert (
        SUPPORTED_ASSETS["eip155:8453"]["USDC"]["contract"]
        == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    )
    assert (
        SUPPORTED_ASSETS["eip155:8453"]["USDT"]["contract"]
        == "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2"
    )
    assert (
        SUPPORTED_ASSETS["eip155:42161"]["ARB"]["contract"]
        == "0x912CE59144191C1204E64559FE8253a0e49E6548"
    )
    assert (
        SUPPORTED_ASSETS["solana:mainnet"]["USDC"]["contract"]
        == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    )
    assert (
        SUPPORTED_ASSETS["solana:mainnet"]["USDT"]["contract"]
        == "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    )
    assert (
        SUPPORTED_ASSETS["tron:mainnet"]["USDT"]["contract"] == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    )


def test_caip2_normalization() -> None:
    """Legacy network names normalize to CAIP-2 ids; ids pass through."""
    assert normalize_network_id("base") == "eip155:8453"
    assert normalize_network_id("solana") == "solana:mainnet"
    assert normalize_network_id("tron") == "tron:mainnet"
    assert normalize_network_id("eip155:42161") == "eip155:42161"
    assert normalize_network_id("") == ""
    assert CAIP2_NETWORK_IDS["arbitrum"] == "eip155:42161"


def test_asset_support_lookup() -> None:
    assert is_asset_supported("solana", "USDC") is True
    assert is_asset_supported("tron", "USDT") is True
    assert is_asset_supported("base", "ARB") is False
    assert is_asset_supported("eip155:42161", "ARB") is True
    entry = resolve_asset_entry("solana:mainnet", "usdt")
    assert entry is not None
    assert entry["verification"] == "spl"
    assert resolve_asset_entry("base", "BOGUS") is None


def test_multi_asset_accepts_include_solana_tron() -> None:
    """Multi-asset accepts quote Solana/TRON assets with USD-equivalent amounts."""
    accepts = build_multi_asset_accepts("scrape", "https://pry.dev/api/scrape")
    by_key = {(a["network"], a["asset"]): a for a in accepts}
    assert ("solana:mainnet", "USDC") in by_key
    assert ("tron:mainnet", "USDT") in by_key
    sol = by_key[("solana:mainnet", "USDC")]
    assert sol["network"] == "solana:mainnet"
    assert int(sol["maxAmountRequired"]) > 0
    assert sol["extra"]["verification"] == "spl"
    assert sol["extra"]["usdPerUnit"] == 1.0
    tron = by_key[("tron:mainnet", "USDT")]
    assert tron["extra"]["verification"] == "trc20"
    arb = by_key[("eip155:42161", "ARB")]
    # ARB is quoted at its USD-per-unit rate (18 decimals).
    assert arb["extra"]["usdPerUnit"] > 0
    assert arb["extra"]["decimals"] == 18


def test_multi_asset_payment_required_body() -> None:
    """multi_asset=True challenge carries CAIP-2 accepts + surface tables."""
    body = build_payment_required("scrape", multi_asset=True)
    assert body["x402Version"] == 1
    networks = {a["network"] for a in body["accepts"]}
    assert "eip155:8453" in networks
    assert "solana:mainnet" in networks
    assert "tron:mainnet" in networks
    assert "networks" in body
    assert "supported_assets" in body
    # Legacy single-asset path is unchanged.
    legacy = build_payment_required("scrape")
    legacy_networks = {a["network"] for a in legacy["accepts"]}
    assert "base" in legacy_networks
    assert "solana" in legacy_networks
    assert "networks" not in legacy


def test_multi_asset_solana_tron_challenge_header() -> None:
    """Solana/TRON challenge headers round-trip per the x402 spec."""
    body = build_payment_required("scrape", multi_asset=True)
    encoded = _encode_payment_required_body(body)
    decoded = json.loads(base64.b64decode(encoded).decode())
    assert decoded == body
    tron = next(a for a in decoded["accepts"] if a["network"] == "tron:mainnet")
    for field in ("scheme", "network", "maxAmountRequired", "resource", "payToAddress", "asset"):
        assert field in tron


def test_per_network_per_asset_price_override() -> None:
    """X402_PRICING can express per-network per-asset price overrides."""
    base = resolve_price_usd("scrape")
    assert base == X402_PRICING["scrape"]["price_usd"]
    # No override configured → base price applies everywhere.
    assert resolve_price_usd("scrape", "solana:mainnet", "USDC") == base
    # Override applies only to its exact network+asset pair.
    X402_PRICING["scrape"]["prices"] = {
        "eip155:137": {"USDC": base / 2},
    }
    try:
        assert resolve_price_usd("scrape", "polygon", "USDC") == base / 2
        assert resolve_price_usd("scrape", "eip155:137", "USDC") == base / 2
        assert resolve_price_usd("scrape", "base", "USDC") == base
        assert resolve_price_usd("scrape", "eip155:137", "USDT") == base
    finally:
        X402_PRICING["scrape"].pop("prices", None)


def test_multi_asset_validate_client_amount() -> None:
    """Underpayment validation uses table decimals + USD-per-unit per network."""
    # Solana USDC (6 decimals, 1:1) — same as legacy.
    ok, _ = validate_client_amount("scrape", 0.001, asset="USDC", network="solana:mainnet")
    assert ok
    ok, reason = validate_client_amount("scrape", 0.0001, asset="USDC", network="solana:mainnet")
    assert not ok
    assert "underpayment" in reason
    # Arbitrum ARB (18 decimals, usd_per_unit 0.6) — amount converted correctly.
    arb_ok, arb_reason = validate_client_amount("scrape", 0.01, asset="ARB", network="arbitrum")
    assert arb_ok, arb_reason
    # Unknown pair falls back to legacy behavior (no crash, still enforced).
    ok, _ = validate_client_amount("scrape", 0.01, asset="ARB", network="base")
    assert ok


def test_asset_to_atomic_uses_table() -> None:
    """asset_to_atomic uses table decimals + USD-per-unit for supported pairs."""
    usdc_atomic = asset_to_atomic(0.001, "USDC", "solana:mainnet")
    assert usdc_atomic == 1000  # 6 decimals, 1:1
    arb_atomic = asset_to_atomic(0.001, "ARB", "eip155:42161")
    arb_unit = X402_ASSET_USD_PER_UNIT["ARB"]
    assert arb_atomic == round(0.001 / arb_unit * 10**18)
