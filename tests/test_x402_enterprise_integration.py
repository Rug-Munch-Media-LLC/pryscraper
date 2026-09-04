"""Enterprise integration test — full x402 payment lifecycle.

Exercises the complete happy path end-to-end with mocked facilitator:
hooks (pre/post verify + settle), verify_payment, settle_payment,
batch channel create/claim/refund, and PaymentInfo expiry/fee validation.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pry.payments.x402.batch import (
    BatchChannel,
    claim_channel,
    create_channel,
    get_channel,
    refund_channel,
)
from pry.payments.x402.handler import X402Handler
from pry.payments.x402.scheme import PaymentInfo


@pytest.mark.asyncio
async def test_full_payment_lifecycle() -> None:
    """Single comprehensive test covering the full x402 payment lifecycle."""
    # ── 1. Create X402Handler with temp paths ──────────────────────────────
    tmp = tempfile.TemporaryDirectory()
    payments_file = Path(tmp.name) / "payments.jsonl"
    settlements_file = Path(tmp.name) / "settlements.jsonl"

    router = MagicMock()
    router.verify = AsyncMock(return_value={"verified": True})
    router.settle = AsyncMock(return_value={"success": True, "tx_hash": "0xtest"})

    handler = X402Handler(
        wallet="0xtestwallet",
        facilitator_url="https://facilitator.example.com",
        router=router,
        payments_file=payments_file,
        settlements_file=settlements_file,
    )
    assert handler.payments_file == payments_file
    assert handler.settlements_file == settlements_file

    # ── 2. Register pre-verify hook ────────────────────────────────────────
    pre_verify_hook = MagicMock(return_value=None)
    handler.on_pre_verify(pre_verify_hook)

    # ── 3. Verify payment (router.verify mocked to verified=True) ─────────
    with patch("pry.payments.x402.handler.fire_settlement_webhook", new=AsyncMock()):
        verify_result = await handler.verify_payment(
            payment_id="pay_lifecycle_1",
            tx_hash="0xtest",
            network="base",
            asset="USDC",
            amount_usd=0.01,
            caller_key="caller-1",
        )
    assert verify_result["verified"] is True
    router.verify.assert_awaited_once()

    # Pre-verify hook was called with the verify context
    pre_verify_hook.assert_called_once()
    call_kwargs = pre_verify_hook.call_args.kwargs
    assert call_kwargs["payment_id"] == "pay_lifecycle_1"
    assert call_kwargs["tx_hash"] == "0xtest"

    # ── 4. Assert post-verify hook fires ───────────────────────────────────
    post_verify_hook = MagicMock(return_value=None)
    handler.on_post_verify(post_verify_hook)
    # Re-verify with a fresh payment_id + tx to trigger the post hook
    with patch("pry.payments.x402.handler.fire_settlement_webhook", new=AsyncMock()):
        verify_result_2 = await handler.verify_payment(
            payment_id="pay_lifecycle_2",
            tx_hash="0xtest2",
            network="base",
            asset="USDC",
            amount_usd=0.01,
            caller_key="caller-1",
        )
    assert verify_result_2["verified"] is True
    post_verify_hook.assert_called_once()
    record = post_verify_hook.call_args.args[0]
    assert record["payment_id"] == "pay_lifecycle_2"
    assert record["verified"] is True

    # ── 5. Register pre-settle hook ────────────────────────────────────────
    pre_settle_hook = MagicMock(return_value=None)
    handler.on_pre_settle(pre_settle_hook)

    # ── 6. Settle payment (router.settle mocked to success) ────────────────
    with patch("pry.payments.x402.handler.fire_settlement_webhook", new=AsyncMock()):
        settle_result = await handler.settle_payment(
            payment_id="pay_lifecycle_2",
            tx_hash="0xtest2",
            network="base",
            asset="USDC",
            amount_usd=0.01,
        )
    assert settle_result["success"] is True
    assert settle_result["tx_hash"] == "0xtest"
    router.settle.assert_awaited_once()

    # Pre-settle hook was called with the settle context
    pre_settle_hook.assert_called_once()
    settle_kwargs = pre_settle_hook.call_args.kwargs
    assert settle_kwargs["payment_id"] == "pay_lifecycle_2"
    assert settle_kwargs["tx_hash"] == "0xtest2"

    # ── 7. Assert post-settle hook fires ───────────────────────────────────
    post_settle_hook = MagicMock(return_value=None)
    handler.on_post_settle(post_settle_hook)
    with patch("pry.payments.x402.handler.fire_settlement_webhook", new=AsyncMock()):
        await handler.settle_payment(
            payment_id="pay_lifecycle_3",
            tx_hash="0xtest3",
            network="base",
            asset="USDC",
            amount_usd=0.01,
        )
    post_settle_hook.assert_called_once()
    settlement_record = post_settle_hook.call_args.args[0]
    assert settlement_record["success"] is True
    assert settlement_record["payment_id"] == "pay_lifecycle_3"

    # ── 8. Batch channel: create → claim 50 → refund ───────────────────────
    channel: BatchChannel = create_channel(chain_id="8453", depositor="0xdepositor")
    assert channel.status == "open"
    assert get_channel(channel.channel_id) is channel

    claim = claim_channel(channel.channel_id, 50)
    assert claim["success"] is True
    assert claim["cumulative_claimed"] == 50
    assert claim["remaining"] == channel.max_claims_per_batch - 50

    refund = refund_channel(channel.channel_id)
    assert refund["success"] is True
    assert refund["status"] == "refunded"
    assert refund["remaining"] == channel.max_claims_per_batch - 50

    # Post-refund claims fail closed
    post_refund_claim = claim_channel(channel.channel_id, 1)
    assert post_refund_claim["success"] is False

    # ── 9. PaymentInfo: expiry + fee validation ────────────────────────────
    now_ts = 1_700_000_000
    info = PaymentInfo(
        payer="0xpayer",
        payee="0xpayee",
        amount_usd=1.0,
        asset="USDC",
        network="base",
        pre_approval_expiry=now_ts + 100,
        authorization_expiry=now_ts + 200,
        refund_expiry=now_ts + 300,
        min_fee_bps=10,
        max_fee_bps=500,
    )
    assert not info.is_expired(ts=now_ts)
    assert info.is_expired(ts=now_ts + 201)
    assert info.validate_fee(100) is True
    assert info.validate_fee(5) is False
    assert info.validate_fee(600) is False

    tmp.cleanup()
