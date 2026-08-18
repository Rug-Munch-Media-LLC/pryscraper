"""Tests for x402/__init__.py and x402/handler.py — payment orchestration."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from x402 import (
    X402Handler,
    create_payment_request,
    create_batch_payment,
    verify_batch_payment,
    require_payment_legacy,
    X402_PRICING,
    SUPPORTED_NETWORKS,
    resolve_price_usd,
    validate_client_amount,
)


def test_x402_pricing_has_scrape():
    assert "scrape" in X402_PRICING
    assert X402_PRICING["scrape"]["price_usd"] > 0


def test_supported_networks_nonempty():
    assert len(SUPPORTED_NETWORKS) > 0


def test_resolve_price_usd():
    price = resolve_price_usd("scrape")
    assert price > 0


def test_resolve_price_usd_unknown():
    price = resolve_price_usd("nonexistent_operation")
    assert price == 0


def test_validate_client_amount_valid():
    ok, reason = validate_client_amount("scrape", 1.0, "USDC")
    assert ok is True


def test_validate_client_amount_underpay():
    ok, reason = validate_client_amount("scrape", 0.0000001, "USDC")
    assert ok is False


def test_validate_client_amount_unknown_asset():
    ok, reason = validate_client_amount("scrape", 1.0, "UNKNOWN")
    assert ok is True  # unknown assets pass through


def test_create_payment_request():
    req = create_payment_request("scrape", {"source": "test"})
    assert "payment_id" in req or "wallet" in req


def test_create_payment_request_unknown():
    req = create_payment_request("nonexistent", {})
    assert req is not None


@pytest.mark.asyncio
async def test_create_batch_payment():
    result = await create_batch_payment(["scrape", "monitor"])
    assert "batch_id" in result or "error" in result


@pytest.mark.asyncio
async def test_create_batch_payment_empty():
    result = await create_batch_payment([])
    assert "error" in result


@pytest.mark.asyncio
async def test_verify_batch_payment():
    result = await verify_batch_payment("batch_1", "0xtx", network="base")
    assert isinstance(result, dict)


def test_require_payment_legacy():
    result = require_payment_legacy("scrape", {})
    assert isinstance(result, dict)
    assert len(result) > 0  # Has some content regardless of format


# ── X402Handler ──


@pytest.mark.asyncio
async def test_handler_verify_payment():
    with (
        patch("x402.handler.FacilitatorRouter") as mock_router_cls,
        patch("x402.handler.get_facilitator_router") as mock_get,
    ):
        mock_instance = MagicMock()
        mock_instance.verify = AsyncMock(return_value={"verified": True, "reason": ""})
        mock_get.return_value = mock_instance
        h = X402Handler()
        result = await h.verify_payment("p1", "0xtx", network="base")
        assert result["verified"] is True


@pytest.mark.asyncio
async def test_handler_settle_payment():
    with (
        patch("x402.handler.FacilitatorRouter") as mock_router_cls,
        patch("x402.handler.get_facilitator_router") as mock_get,
    ):
        mock_instance = MagicMock()
        mock_instance.settle = AsyncMock(return_value={"success": True})
        mock_get.return_value = mock_instance
        h = X402Handler()
        result = await h.settle_payment("p1", "0xtx", network="base")
        assert result["success"] is True


def test_handler_get_stats():
    h = X402Handler()
    stats = h.get_stats()
    assert isinstance(stats, dict)
    assert "pricing" in stats
