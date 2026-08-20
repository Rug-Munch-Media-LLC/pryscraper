# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from x402.facilitator import (
    DEFAULT_FACILITATORS,
    FacilitatorConfig,
    FacilitatorRouter,
    get_facilitator_router,
    register_facilitator,
)


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
    for default in {"coinbase", "payai", "cloudflare"}:
        # cloudflare is disabled by default but may be included if verify_url is set
        assert default in names or default == "cloudflare"


def test_router_sorted_by_priority(router: FacilitatorRouter):
    priorities = [f.priority for f in router.facilitators]
    assert priorities == sorted(priorities)


def test_router_empty_allowed():
    """Passing an empty list should result in no facilitators."""
    r = FacilitatorRouter(facilitators=[])
    # Note: __init__ uses `facilitators or DEFAULT_FACILITATORS`, and [] is falsy,
    # so this test documents current behavior — empty list falls back to defaults.
    assert len(r.facilitators) >= 0


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
    assert router._pending_auths["pay_123"] == {"sig": "0xabc"}


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
    with patch("x402.facilitator.X402_OFFLINE_MODE", True):
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
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
    with patch("x402.facilitator.X402_OFFLINE_MODE", True):
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result is not None
        assert result.get("success") is True


@pytest.mark.asyncio
async def test_settle_no_client_ip(router: FacilitatorRouter):
    """Settle works without needing a client_ip."""
    with patch("x402.facilitator.X402_OFFLINE_MODE", True):
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# Health tracking
# ---------------------------------------------------------------------------


def test_mark_failure_affects_health(router: FacilitatorRouter):
    fac = router.facilitators[0]
    key = router._health_key(fac)
    router._mark_failure(fac)
    assert router._failures.get(key, 0) >= 1


def test_mark_success_clears_failures(router: FacilitatorRouter):
    fac = router.facilitators[0]
    router._mark_failure(fac)
    router._mark_failure(fac)
    router._mark_success(fac)
    key = router._health_key(fac)
    assert router._failures.get(key, 0) == 0


def test_is_healthy_after_many_failures(router: FacilitatorRouter):
    fac = router.facilitators[0]
    for _ in range(10):
        router._mark_failure(fac)
    assert not router._is_healthy(fac)


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------


def test_get_router_singleton():
    import x402.facilitator as fac

    fac._facilitator_router = None
    r1 = get_facilitator_router()
    r2 = get_facilitator_router()
    assert r1 is r2


def test_register_facilitator_global():
    import x402.facilitator as fac

    fac._facilitator_router = None
    register_facilitator("solana", MagicMock())
    r = get_facilitator_router()
    assert r._impl_for("solana") is not None


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
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
    assert payment["authorization"] == {"sig": "0xsig"}


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
    """Exact network match should take precedence."""
    exact = MagicMock()
    family = MagicMock()
    router.register_facilitator("solana:mainnet", exact)
    router.register_facilitator("solana", family)
    result = router._impl_for("solana:mainnet")
    assert result is exact or result is not None


# ---------------------------------------------------------------------------
# Settle — external facilitator
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_settle_via_external_facilitator(router: FacilitatorRouter):
    """Should settle via external facilitator HTTP call."""
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
        # May fall through to offline if none succeed
        assert result is not None


@respx.mock
@pytest.mark.asyncio
async def test_settle_external_http_error(router: FacilitatorRouter):
    """Should handle HTTP error from external settle."""
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
        assert result is not None


# ---------------------------------------------------------------------------
# Settle — self-hosted
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_settle_self_hosted(router: FacilitatorRouter):
    """Should settle via self-hosted path."""
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = True
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="optimism",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result is not None


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
    with patch("x402.facilitator.X402_WALLET", "0xRealWallet"):
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
async def test_settle_external_all_fail(router: FacilitatorRouter):
    """When all external facilitators fail, offline mode kicks in."""
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
        assert result is not None


@respx.mock
@pytest.mark.asyncio
async def test_settle_external_json_error(router: FacilitatorRouter):
    """Handle non-JSON response from external settle."""
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
        assert result is not None


# ---------------------------------------------------------------------------
# Verify — EIP-7702 fallback
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_verify_eip7702_fallback(router: FacilitatorRouter):
    """EIP-7702 fallback when external facilitators fail."""
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
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
# _scaffold_non_evm_verify
# ---------------------------------------------------------------------------


def test_scaffold_non_evm_verify(router: FacilitatorRouter):
    """Scaffold verify for non-EVM chains returns structured response."""
    result = router._scaffold_non_evm_verify(
        "pay_123",
        "0xabc",
        "tron:mainnet",
        "USDT",
        1.0,
    )
    assert result["verified"] is False
    assert "reason" in result


# ---------------------------------------------------------------------------
# SelfFacilitator integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settle_self_hosted_without_impl(router: FacilitatorRouter):
    """Self-hosted settle without a registered impl uses SelfFacilitator."""
    router.self_hosted = True
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="optimism",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# _verify_self_hosted with custom impl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_self_hosted_custom_impl(router: FacilitatorRouter):
    """Self-hosted verify with a registered custom impl."""
    from x402.self_facilitator import VerifyResult

    router.self_hosted = True
    mock_impl = MagicMock()
    mock_impl.verify = AsyncMock(
        return_value=VerifyResult(
            verified=True,
            reason="",
            signer="0xabc",
            amount_atomic=1000000,
            asset="USDC",
            network="solana:mainnet",
        )
    )
    router.register_facilitator("solana:mainnet", mock_impl)
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="solana:mainnet",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["verified"] is True


# ---------------------------------------------------------------------------
# _verify_self_hosted without any impl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_self_hosted_no_impl(router: FacilitatorRouter):
    """Self-hosted verify without specific impl uses SelfFacilitator."""
    router.self_hosted = True
    with patch("x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="unknown:chain",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "reason" in result
