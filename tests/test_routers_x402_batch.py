"""Batch payment/verify tests for routers/x402.py.

Covers the ``/v1/x402/batch-payment`` and ``/v1/x402/batch-verify`` endpoints.

Sibling of ``test_routers_x402.py`` (health, pricing, single-payment, pay
and catalog endpoints).
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
# POST /v1/x402/batch-payment
# ---------------------------------------------------------------------------


def test_x402_batch_payment():
    response = client.post("/v1/x402/batch-payment", json={"operations": ["scrape", "monitor"]})
    assert response.status_code == 200
    assert "success" in response.json()


def test_x402_batch_payment_not_a_list():
    response = client.post("/v1/x402/batch-payment", json={"operations": "not-a-list"})
    assert response.status_code in (400, 422)


def test_x402_batch_payment_empty_list():
    response = client.post("/v1/x402/batch-payment", json={"operations": []})
    assert response.status_code == 200
    body = response.json()
    # No valid operations => success=False with an error message.
    assert body.get("success") is False
    assert "error" in body


# ---------------------------------------------------------------------------
# POST /v1/x402/batch-verify
# ---------------------------------------------------------------------------


def test_x402_batch_verify_missing_fields():
    response = client.post("/v1/x402/batch-verify", json={})
    assert response.status_code in (400, 422)


def test_x402_batch_verify_with_fields():
    with _patch_x402():
        response = client.post(
            "/v1/x402/batch-verify",
            json={"batch_id": "test_batch", "tx_hash": "0xabc"},
        )
        assert response.status_code == 200
        assert "success" in response.json()
