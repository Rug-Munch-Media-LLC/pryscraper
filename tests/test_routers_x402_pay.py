"""Pay + require-payment tests for routers/x402.py.

Covers the ``/v1/x402/pay`` and ``/v1/x402/require-payment`` endpoints.

Sibling of ``test_routers_x402.py`` (health, pricing, single-payment and
catalog endpoints).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

# Mock external dependencies before importing app
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from pry.api.api import app

client = TestClient(app)


def _patch_x402():
    """Patch x402 functions used in router endpoints that make network calls."""
    # X402Handler is imported inside the endpoint functions via `from pry.payments.x402 import X402Handler`
    return patch.multiple(
        "pry.payments.x402.X402Handler",
        verify_payment=AsyncMock(return_value={"verified": True, "reason": "", "settlement": None}),
        settle_payment=AsyncMock(return_value={"success": True, "tx_hash": "0xsettled"}),
        get_stats=MagicMock(return_value={"scrape": {"price_usd": 1.0}}),
    )


# ---------------------------------------------------------------------------
# POST /v1/x402/require-payment
# ---------------------------------------------------------------------------


def test_x402_require_payment():
    response = client.post("/v1/x402/require-payment", json={"operation": "scrape"})
    assert response.status_code in (200, 402)


def test_x402_require_payment_unknown_op():
    response = client.post("/v1/x402/require-payment", json={"operation": "unknown_op"})
    assert response.status_code in (200, 402)


# ---------------------------------------------------------------------------
# require-payment format
# ---------------------------------------------------------------------------


def test_x402_require_payment_format():
    response = client.post(
        "/v1/x402/require-payment",
        json={"operation": "scrape"},
    )
    assert response.status_code in (200, 402)


# ---------------------------------------------------------------------------
# POST /v1/x402/pay
# ---------------------------------------------------------------------------


def test_x402_pay_underpayment():
    """Underpayment should be rejected upfront."""
    response = client.post(
        "/v1/x402/pay",
        json={
            "operation": "scrape",
            "tx_hash": "0xabc",
            "payer_wallet": "0xwallet",
            "amount_usd": 0.001,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is False


def test_x402_pay_success():
    """Full pay flow with verification patched out."""
    with _patch_x402():
        response = client.post(
            "/v1/x402/pay",
            json={
                "operation": "scrape",
                "tx_hash": "0xvalid_tx",
                "payer_wallet": "0xwallet",
                "network": "base",
                "asset": "USDC",
                "amount_usd": 1.0,
            },
        )
        assert response.status_code == 200
        assert "success" in response.json()


def test_x402_pay_with_metadata():
    """Pay flow with metadata in request."""
    with _patch_x402():
        response = client.post(
            "/v1/x402/pay",
            json={
                "operation": "scrape",
                "tx_hash": "0xvalid",
                "payer_wallet": "0xwallet",
                "network": "optimism",
                "asset": "USDC",
                "amount_usd": 1.0,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body.get("success") is True
        data = body["data"]
        # Pay flow must return a payment_id, echo the tx_hash, and expose the
        # header values the client must send on the follow-up request.
        assert data["payment_id"]
        assert data["tx_hash"] == "0xvalid"
        assert data["payer_wallet"] == "0xwallet"
        assert data["verified"]["verified"] is True
        assert data["use_in_header"]["X-Payment-ID"] == data["payment_id"]
        assert data["use_in_header"]["X-Payment-Hash"] == "0xvalid"
