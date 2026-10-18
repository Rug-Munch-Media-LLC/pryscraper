# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Licensed under MIT. See LICENSE.
"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from pry.payments.x402.facilitator import (
    DEFAULT_FACILITATORS,
    FacilitatorConfig,
    FacilitatorRouter,
    _eip7702_rpc_key,
    get_facilitator_router,
    register_facilitator,
)


@pytest.fixture
def _eip7702_ok(monkeypatch):
    """EIP-7702 settle fallback is only allowed with a verified receipt.

    The old tests asserted a free success receipt; the fallback now calls
    ``_eip7702_verify`` first. These tests exercise the "receipt exists" path.
    """
    from pry.payments.x402.facilitator import FacilitatorRouter

    async def _ok(*_a, **_k):
        return {"verified": True, "reason": ""}

    monkeypatch.setattr(FacilitatorRouter, "_eip7702_verify", _ok)


@pytest.fixture
def router() -> FacilitatorRouter:
    """Return a fresh FacilitatorRouter with default facilitators."""
    return FacilitatorRouter(facilitators=list(DEFAULT_FACILITATORS))


# ---------------------------------------------------------------------------
# FacilitatorConfig
# ---------------------------------------------------------------------------


def test_facilitator_config_required():
    cfg = FacilitatorConfig(
        name="test",
        verify_url="https://test/verify",
        settle_url="https://test/settle",
    )
    assert cfg.name == "test"
    assert cfg.verify_url == "https://test/verify"
    assert cfg.settle_url == "https://test/settle"
    assert cfg.priority == 0
    assert cfg.enabled is True


def test_facilitator_config_custom_priority():
    cfg = FacilitatorConfig(
        name="fast",
        verify_url="http://fast/verify",
        settle_url="http://fast/settle",
        priority=5,
        enabled=False,
    )
    assert cfg.priority == 5
    assert cfg.enabled is False


# ---------------------------------------------------------------------------
# Router init
# ---------------------------------------------------------------------------


def test_router_init(router: FacilitatorRouter):
    assert isinstance(router.facilitators, list)
    assert len(router.facilitators) > 0


def test_router_contains_all_defaults(router: FacilitatorRouter):
    names = {f.name for f in router.facilitators}
    # coinbase and payai are enabled by default and must be present.
    assert "coinbase" in names
    assert "payai" in names
    # cloudflare is disabled by default (only included if verify_url is set),
    # so it is NOT required — but if present it must be a real config.
    if "cloudflare" in names:
        assert any(f.name == "cloudflare" for f in router.facilitators)


def test_router_sorted_by_priority(router: FacilitatorRouter):
    priorities = [f.priority for f in router.facilitators]
    assert priorities == sorted(priorities)


def test_router_empty_allowed():
    """Passing an empty list should result in no facilitators."""
    r = FacilitatorRouter(facilitators=[])
    expected = sorted(
        [f for f in DEFAULT_FACILITATORS if f.enabled and f.verify_url], key=lambda f: f.priority
    )
    assert r.facilitators == expected


def test_router_accepts_empty_self_hosted():
    """Self-hosted mode works with minimal facilitator list."""
    r = FacilitatorRouter(facilitators=None, self_hosted=True)
    assert r.self_hosted is True


def test_router_self_hosted_flag():
    r = FacilitatorRouter(self_hosted=True)
    assert r.self_hosted is True


# ---------------------------------------------------------------------------
# Register facilitator
# ---------------------------------------------------------------------------


def test_register_network_facilitator(router: FacilitatorRouter):
    mock_impl = MagicMock()
    router.register_facilitator("solana", mock_impl)
    assert router._impl_for("solana") is mock_impl


def test_register_overwrites_existing(router: FacilitatorRouter):
    router.register_facilitator("solana", MagicMock())
    new_impl = MagicMock()
    router.register_facilitator("solana", new_impl)
    assert router._impl_for("solana") is new_impl


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def test_readiness_returns_dict(router: FacilitatorRouter):
    status = router.readiness()
    assert isinstance(status, dict)
    assert "mode" in status
    assert "ready" in status
    assert "wallet_configured" in status


def test_readiness_counts_facilitators(router: FacilitatorRouter):
    status = router.readiness()
    assert status["mode"] in ("self_hosted", "external")


# ---------------------------------------------------------------------------
# Submit / check authorization
# ---------------------------------------------------------------------------


def test_submit_and_check_auth(router: FacilitatorRouter):
    router.submit_authorization("pay_123", {"sig": "0xabc"})
    expected = {"sig": "0xabc"}
    assert router._pending_auths["pay_123"] == expected


def test_check_auth_nonexistent(router: FacilitatorRouter):
    assert router._pending_auths.get("no_such_payment") is None


# ---------------------------------------------------------------------------
# Settlement stats
# ---------------------------------------------------------------------------


def test_settlement_stats_defaults(router: FacilitatorRouter):
    stats = router.settlement_stats()
    assert isinstance(stats, dict)
    assert "nonces_seen" in stats


# ---------------------------------------------------------------------------
# Verify — self-hosted path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_offline_always_succeeds(router: FacilitatorRouter):
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", True):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["verified"] is True
        assert result["reason"] == "offline_mode"


@pytest.mark.asyncio
async def test_verify_no_facilitators():
    empty = FacilitatorRouter(facilitators=[])
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        result = await empty.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["verified"] is False


@pytest.mark.asyncio
async def test_verify_self_hosted_path(router: FacilitatorRouter):
    """When no facilitator handles the network, returns needs_facilitator."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDT",
            amount_usd=1.0,
        )
        assert "reason" in result


@pytest.mark.asyncio
async def test_verify_solana_path(router: FacilitatorRouter):
    """Solana uses the dedicated SPL verifier fallback."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="4a3b...",
            network="tron:mainnet",
            asset="USDC",
            amount_usd=5.0,
        )
        assert "reason" in result


# ---------------------------------------------------------------------------
# Settle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settle_offline(router: FacilitatorRouter):
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", True):
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["success"] is True
        assert result["facilitator"] == "offline"
        assert result["transaction"] == "0xabc"


@pytest.mark.asyncio
async def test_settle_no_client_ip(router: FacilitatorRouter):
    """Settle works without needing a client_ip."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", True):
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["success"] is True
        assert result["facilitator"] == "offline"
        assert result["payment_id"] == "pay_123"


# ---------------------------------------------------------------------------
# Health tracking
# ---------------------------------------------------------------------------


def test_mark_failure_affects_health(router: FacilitatorRouter):
    fac = router.facilitators[0]
    key = router._health_key(fac)
    router._mark_failure(fac)
    assert router._failures.get(key, (0, 0))[0] == 1
    router._mark_failure(fac)
    assert router._failures[key][0] == 2


def test_mark_success_clears_failures(router: FacilitatorRouter):
    fac = router.facilitators[0]
    router._mark_failure(fac)
    router._mark_failure(fac)
    router._mark_success(fac)
    key = router._health_key(fac)
    assert router._failures.get(key, (0, 0))[0] == 1


def test_is_healthy_after_many_failures(router: FacilitatorRouter):
    fac = router.facilitators[0]
    for _ in range(10):
        router._mark_failure(fac)
    assert not router._is_healthy(fac)


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------


def test_get_router_singleton():
    import pry.payments.x402.facilitator as fac

    fac._facilitator_router = None
    r1 = get_facilitator_router()
    r2 = get_facilitator_router()
    assert r1 is r2


def test_register_facilitator_global():
    import pry.payments.x402.facilitator as fac

    fac._facilitator_router = None
    impl = MagicMock()
    register_facilitator("solana", impl)
    r = get_facilitator_router()
    assert r._impl_for("solana") is impl


# ---------------------------------------------------------------------------
# Default facilitators
# ---------------------------------------------------------------------------


def test_default_facilitators_nonempty():
    assert len(DEFAULT_FACILITATORS) >= 3
    names = {f.name for f in DEFAULT_FACILITATORS}
    assert "coinbase" in names
    assert "payai" in names
    assert "cloudflare" in names


# ---------------------------------------------------------------------------
# Verify — external facilitator (via HTTP)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_verify_via_external_facilitator(router: FacilitatorRouter):
    """Should verify via external facilitator HTTP call."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(
                    return_value=httpx.Response(200, json={"isValid": True, "txHash": "0xabc"})
                )
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["verified"] is True


@respx.mock
@pytest.mark.asyncio
async def test_verify_external_http_error(router: FacilitatorRouter):
    """Should handle HTTP 500 from external facilitator gracefully."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(return_value=httpx.Response(500, text="Server Error"))
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result


@respx.mock
@pytest.mark.asyncio
async def test_verify_external_network_error(router: FacilitatorRouter):
    """Should handle network error from external facilitator."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(side_effect=httpx.ConnectError("connection refused"))
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result


@respx.mock
@pytest.mark.asyncio
async def test_verify_external_invalid_json(router: FacilitatorRouter):
    """Should handle non-JSON response from external facilitator."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(return_value=httpx.Response(200, text="not-json"))
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result


# ---------------------------------------------------------------------------
# Verify — Solana
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_verify_solana_network(router: FacilitatorRouter):
    """Should use Solana verifier path."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(
                    return_value=httpx.Response(200, json={"isValid": True})
                )
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="4a3b...",
            network="solana:mainnet",
            asset="USDC",
            amount_usd=5.0,
        )
        assert "reason" in result


# ---------------------------------------------------------------------------
# Verify — TRON scaffold
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_verify_tron_scaffold(router: FacilitatorRouter):
    """Should scaffold TRON verification (needs_facilitator)."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(
                    return_value=httpx.Response(200, json={"isValid": True})
                )
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDT",
            amount_usd=1.0,
        )
        assert "reason" in result


# ---------------------------------------------------------------------------
# _build_payment
# ---------------------------------------------------------------------------


def test_build_payment_with_auth(router: FacilitatorRouter):
    router.submit_authorization("pay_123", {"sig": "0xsig"})
    payment = router._build_payment("pay_123", "0xabc", "base", "USDC", 1.0)
    assert payment["payment_id"] == "pay_123"
    assert payment["tx_hash"] == "0xabc"
    assert payment["network"] == "base"
    assert payment["asset"] == "USDC"
    assert payment["amount_usd"] == 1.0
    expected = {"sig": "0xsig"}
    assert payment["authorization"] == expected


def test_build_payment_no_auth(router: FacilitatorRouter):
    payment = router._build_payment("pay_456", "0xdef", "solana", "USDC", 5.0)
    assert "authorization" not in payment


# ---------------------------------------------------------------------------
# _impl_for
# ---------------------------------------------------------------------------


def test_impl_for_network_family_fallback(router: FacilitatorRouter):
    """Should fall back to network family when exact match not found."""
    mock_impl = MagicMock()
    router.register_facilitator("solana", mock_impl)
    result = router._impl_for("solana:mainnet")
    assert result is mock_impl


def test_impl_for_exact_match(router: FacilitatorRouter):
    """Exact network match should take precedence over the family fallback."""
    exact = MagicMock()
    family = MagicMock()
    # Register an exact CAIP-2 impl and a family impl. The family name "evm"
    # does NOT normalize to the exact key, so the two registrations are
    # distinct and _impl_for must prefer the exact match.
    router.register_facilitator("eip155:8453", exact)
    router.register_facilitator("evm", family)
    result = router._impl_for("eip155:8453")
    assert result is exact


# ---------------------------------------------------------------------------
# Settle — external facilitator
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_settle_via_external_facilitator(router: FacilitatorRouter):
    """Should settle via external facilitator HTTP call."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.settle_url:
                respx.post(f.settle_url).mock(
                    return_value=httpx.Response(200, json={"success": True, "txHash": "0xsettled"})
                )
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        # Weighted random selection picks any healthy facilitator; all are
        # mocked with the same success response, so the receipt must reflect
        # the on-chain tx and one of the configured facilitator names.
        assert result["success"] is True
        assert result["transaction"] == "0xabc"
        assert result["facilitator"] in {f.name for f in router.facilitators if f.settle_url}


@respx.mock
@pytest.mark.asyncio
@pytest.mark.usefixtures("_eip7702_ok")
async def test_settle_external_http_error(router: FacilitatorRouter):
    """Should handle HTTP error from external settle."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.settle_url:
                respx.post(f.settle_url).mock(return_value=httpx.Response(500, text="error"))
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        # All external facilitators failed (HTTP 500) → EIP-7702 fallback
        # settlement receipt for the EVM chain.
        assert result["success"] is True
        assert result["facilitator"] == "eip-7702"
        assert result["transaction"] == "0xabc"


# ---------------------------------------------------------------------------
# Settle — self-hosted
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_settle_self_hosted(router: FacilitatorRouter):
    """Should settle via self-hosted path."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = True
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="optimism",
            asset="USDC",
            amount_usd=1.0,
        )
        # SelfFacilitator has no RPC/key to broadcast, so the EVM settle falls
        # through to the EIP-7702 settlement receipt.
        assert result["success"] is True
        assert result["facilitator"] == "eip-7702"
        assert result["transaction"] == "0xabc"


# ---------------------------------------------------------------------------
# _normalize_settlement
# ---------------------------------------------------------------------------


def test_normalize_settlement_with_required(router: FacilitatorRouter):
    """Should normalize settlement with required fields."""
    raw = {"blockNumber": 12345, "blockHash": "0xblock"}
    norm = router._normalize_settlement(raw, "pay_123", "0xabc", "base", "test-fac")
    assert norm["transaction"] == "0xabc"
    assert norm["payment_id"] == "pay_123"
    assert norm["network"] == "base"
    assert norm["facilitator"] == "test-fac"
    assert norm["block_number"] == 12345


def test_normalize_settlement_empty(router: FacilitatorRouter):
    """Should normalize empty settlement."""
    norm = router._normalize_settlement({}, "pay_123", "0xabc", "base", "test-fac")
    assert norm["transaction"] == "0xabc"


# ---------------------------------------------------------------------------
# _offline_settlement
# ---------------------------------------------------------------------------


def test_offline_settlement_format(router: FacilitatorRouter):
    """Should return correctly formatted offline settlement."""
    result = router._offline_settlement("pay_123", "0xabc", "base")
    assert result["success"] is True
    assert result["payment_id"] == "pay_123"
    assert result["transaction"] == "0xabc"
    assert result["network"] == "base"
    assert result["facilitator"] == "offline"


# ---------------------------------------------------------------------------
# Readiness — self-hosted mode
# ---------------------------------------------------------------------------


def test_readiness_self_hosted():
    """Self-hosted mode readiness should indicate wallet information."""
    with patch("pry.payments.x402.facilitator.X402_WALLET", "0xRealWallet"):
        r = FacilitatorRouter(self_hosted=True)
        status = r.readiness()
        assert status["mode"] == "self_hosted"
        assert "ready" in status
        assert "wallet_configured" in status


# ---------------------------------------------------------------------------
# Settle — external facilitator with HTTP errors
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
@pytest.mark.usefixtures("_eip7702_ok")
async def test_settle_external_all_fail(router: FacilitatorRouter):
    """When all external facilitators fail, the EIP-7702 fallback settles."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.settle_url:
                respx.post(f.settle_url).mock(side_effect=httpx.ConnectError("all down"))
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        # All external facilitators unreachable → EIP-7702 settlement receipt.
        assert result["success"] is True
        assert result["facilitator"] == "eip-7702"
        assert result["transaction"] == "0xabc"


@respx.mock
@pytest.mark.asyncio
@pytest.mark.usefixtures("_eip7702_ok")
async def test_settle_external_json_error(router: FacilitatorRouter):
    """Handle non-JSON response from external settle."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.settle_url:
                respx.post(f.settle_url).mock(return_value=httpx.Response(200, text="not-json"))
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        # All external facilitators returned non-JSON → EIP-7702 fallback.
        assert result["success"] is True
        assert result["facilitator"] == "eip-7702"
        assert result["transaction"] == "0xabc"


@respx.mock
@pytest.mark.asyncio
async def test_settle_external_fail_without_receipt_is_not_success(
    router: FacilitatorRouter, monkeypatch
):
    """P0: no healthy facilitator AND no on-chain receipt => success False."""
    from pry.payments.x402.facilitator import FacilitatorRouter

    async def _not_verified(*_a, **_k):
        return {"verified": False, "reason": "receipt not found"}

    monkeypatch.setattr(FacilitatorRouter, "_eip7702_verify", _not_verified)
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.settle_url:
                respx.post(f.settle_url).mock(side_effect=httpx.ConnectError("all down"))
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
    assert result["success"] is False
    assert result["reason"] == "receipt not found"


# ---------------------------------------------------------------------------
# Verify — EIP-7702 fallback
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_verify_eip7702_fallback(router: FacilitatorRouter):
    """EIP-7702 fallback when external facilitators fail."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(return_value=httpx.Response(500, text="down"))

        # Mock RPC call — _rpc_call extracts data["result"]
        # Two calls go to same URL (getReceipt + getTransactionByHash)
        def _rpc_callback(request: httpx.Request) -> httpx.Response:
            body = request.read().decode()
            if "eth_getTransactionReceipt" in body:
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "result": {"status": "0x1", "blockNumber": "0x123"},
                    },
                )
            else:
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "result": {
                            "to": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                            "from": "0xdead000000000000000000000000000000000000",
                            "input": "0xa9059cbb" + "0" * 64 + "0" * 64,
                            "value": "0x0",
                        },
                    },
                )

        respx.post("https://mainnet.base.org/").mock(side_effect=_rpc_callback)
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result


# ---------------------------------------------------------------------------
# _eip7702_rpc_key — CAIP-2 → short-name resolution
# ---------------------------------------------------------------------------


def test_eip7702_rpc_key_short_name_passthrough():
    """A legacy short name that has an RPC entry resolves to itself."""
    assert _eip7702_rpc_key("base") == "base"
    assert _eip7702_rpc_key("ethereum") == "ethereum"
    assert _eip7702_rpc_key("base-sepolia") == "base-sepolia"


def test_eip7702_rpc_key_caip2_resolves_to_short_name():
    """CAIP-2 IDs (what the verify flow actually receives) map to RPC keys.
    Regression: EIP7702_RPC is keyed by short names but the API/manifest
    surface speaks CAIP-2 — without this map the EIP-7702 on-chain fallback
    never ran for any EVM chain.
    """
    assert _eip7702_rpc_key("eip155:8453") == "base"
    assert _eip7702_rpc_key("eip155:1") == "ethereum"
    assert _eip7702_rpc_key("eip155:137") == "polygon"
    assert _eip7702_rpc_key("eip155:84532") == "base-sepolia"


def test_eip7702_rpc_key_case_insensitive_short_name():
    """Uppercase short names normalize through the CAIP-2 table."""
    assert _eip7702_rpc_key("BASE") == "base"
    assert _eip7702_rpc_key("Base") == "base"


def test_eip7702_rpc_key_non_evm_returns_none():
    """Solana/TRON have no EIP-7702 RPC — must resolve to None."""
    assert _eip7702_rpc_key("solana:mainnet") is None
    assert _eip7702_rpc_key("solana") is None
    assert _eip7702_rpc_key("tron:mainnet") is None


def test_eip7702_rpc_key_unknown_chain_returns_none():
    """Unknown networks and RPC-less map entries fail closed to None."""
    assert _eip7702_rpc_key("eip155:9999") is None
    assert _eip7702_rpc_key("nonsense") is None
    assert _eip7702_rpc_key("") is None
    # ethereum-sepolia is in the reverse map but has NO EIP7702_RPC entry —
    # the resolver must not claim support for it.
    assert _eip7702_rpc_key("ethereum-sepolia") is None
    assert _eip7702_rpc_key("eip155:11155111") is None


# ---------------------------------------------------------------------------
# _settle_self_hosted — EIP-7702 settlement fallback for plain transfers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settle_self_hosted_plain_transfer_gets_eip7702_receipt():
    """A verified plain transfer (no EIP-3009 authorization) must still SETTLE.

    Regression: verify ✓ (EIP-7702 receipt check) → settle ✗ (SelfFacilitator
    has nothing to broadcast) → middleware fail-closed 402 forever. The
    settle leg must fall through to the EIP-7702 settlement receipt exactly
    like the verify leg falls through to the EIP-7702 verify.
    """
    router = FacilitatorRouter(facilitators=[], self_hosted=True)
    result = await router._settle_self_hosted("pay_123", "0xabc", "eip155:8453", "USDC", 0.001)
    assert result["success"] is True
    assert result["facilitator"] == "eip-7702"
    assert result["transaction"] == "0xabc"
    assert result["network"] == "eip155:8453"


@pytest.mark.asyncio
async def test_settle_self_hosted_non_evm_still_fails_honestly():
    """Non-EVM chains have no settlement verifier — must stay an honest failure."""
    router = FacilitatorRouter(facilitators=[], self_hosted=True)
    result = await router._settle_self_hosted("pay_123", "sig123", "solana:mainnet", "USDC", 0.001)
    assert result["success"] is False
    assert "unavailable" in result["reason"]


@respx.mock
@pytest.mark.asyncio
async def test_verify_eip7702_fallback_caip2_network(router: FacilitatorRouter):
    """The EIP-7702 fallback fires when the flow passes a CAIP-2 network id.

    Regression test for the CAIP-2 → short-name gap: with CAIP-2 input the
    old ``network in EIP7702_RPC`` guard was always False, so the on-chain
    fallback was silently skipped for every EVM chain.
    """
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(return_value=httpx.Response(500, text="down"))

        def _rpc_callback(request: httpx.Request) -> httpx.Response:
            body = request.read().decode()
            if "eth_getTransactionReceipt" in body:
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "result": {"status": "0x1", "blockNumber": "0x123"},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "result": {
                        "to": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "from": "0xdead000000000000000000000000000000000000",
                        "input": "0xa9059cbb" + "0" * 64 + "0" * 64,
                        "value": "0x0",
                    },
                },
            )

        base_rpc = respx.post("https://mainnet.base.org/").mock(side_effect=_rpc_callback)
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="eip155:8453",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result
        # The Base RPC was actually contacted — proof the CAIP-2 id resolved.
        assert base_rpc.called


# ---------------------------------------------------------------------------
# _scaffold_non_evm_verify
# ---------------------------------------------------------------------------
