"""Tests for x402/__init__.py and x402/handler.py — payment orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pry.payments.x402 import (
    SUPPORTED_NETWORKS,
    X402_PRICING,
    X402Handler,
    create_batch_payment,
    create_payment_request,
    require_payment_legacy,
    resolve_price_usd,
    validate_client_amount,
    verify_batch_payment,
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
    ok, _reason = validate_client_amount("scrape", 1.0, "USDC")
    assert ok is True


def test_validate_client_amount_underpay():
    ok, _reason = validate_client_amount("scrape", 0.0000001, "USDC")
    assert ok is False


def test_validate_client_amount_unknown_asset():
    ok, _reason = validate_client_amount("scrape", 1.0, "UNKNOWN")
    assert ok is True  # unknown assets pass through


def test_create_payment_request():
    req = create_payment_request("scrape", {"source": "test"})
    assert isinstance(req, dict)
    assert "payment_id" in req
    assert req["operation"] == "scrape"
    assert req["asset"] == "USDC"
    assert req["extra"] == {"source": "test"}


def test_create_payment_request_unknown():
    req = create_payment_request("nonexistent", {})
    assert isinstance(req, dict)
    assert "error" in req
    assert "nonexistent" in req["error"]


@pytest.mark.asyncio
async def test_create_batch_payment():
    result = await create_batch_payment(["scrape", "monitor"])
    assert isinstance(result, dict)
    assert "batch_id" in result
    assert result["batch_id"].startswith("batch_")
    # Both operations are valid, so the batch must carry a positive total and
    # a per-operation breakdown covering exactly the requested ops.
    assert result["total_usd"] > 0
    assert {op["operation"] for op in result["operations"]} == {"scrape", "monitor"}
    assert "payment_required" in result


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
    # A valid operation must produce a full 402 response with the payment
    # header and a spec-shaped body — not just "some content".
    assert result["status_code"] == 402
    assert result["headers"]["X-Payment-Required"] == "true"
    assert result["headers"]["X-Payment-Options"] == "x402"
    assert result["body"]["x402"]["operation"] == "scrape"


# ── X402Handler ──


@pytest.mark.asyncio
async def test_handler_verify_payment(tmp_path):
    with (
        patch("pry.payments.x402.handler.FacilitatorRouter"),
        patch("pry.payments.x402.handler.get_facilitator_router") as mock_get,
    ):
        mock_instance = MagicMock()
        mock_instance.verify = AsyncMock(return_value={"verified": True, "reason": ""})
        mock_get.return_value = mock_instance
        h = X402Handler(
            payments_file=tmp_path / "payments.jsonl",
            settlements_file=tmp_path / "settlements.jsonl",
        )
        # Replay-dedup: a fresh tx_hash verifies once…
        result = await h.verify_payment("p1", "0xtx-fresh", network="base")
        assert result["verified"] is True
        # …and the same tx_hash is single-use — the replay is rejected.
        replay = await h.verify_payment("p2", "0xtx-fresh", network="base")
        assert replay["verified"] is False
        assert replay["reason"] == "tx_hash already consumed"


@pytest.mark.asyncio
async def test_handler_settle_payment():
    with (
        patch("pry.payments.x402.handler.FacilitatorRouter"),
        patch("pry.payments.x402.handler.get_facilitator_router") as mock_get,
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
