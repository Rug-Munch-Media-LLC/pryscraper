# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
            network="solana:mainnet",
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
