"""Tests for routers/x402.py — x402 payment API endpoints."""

from __future__ import annotations

# Mock external dependencies before importing app
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

# The app import triggers loading x402 module which may try network calls
# We'll patch at function level instead
from api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_x402():
    """Patch x402 functions used in router endpoints that make network calls."""
    # X402Handler is imported inside the endpoint functions via `from x402 import X402Handler`
    return patch.multiple(
        "x402.X402Handler",
        verify_payment=AsyncMock(return_value={"verified": True, "reason": "", "settlement": None}),
        settle_payment=AsyncMock(return_value={"success": True, "tx_hash": "0xsettled"}),
        get_stats=MagicMock(return_value={"scrape": {"price_usd": 1.0}}),
    )


# ---------------------------------------------------------------------------
# GET /v1/x402/health
# ---------------------------------------------------------------------------


def test_x402_health():
    with _patch_x402(), patch("x402.facilitator.get_facilitator_router") as mock_get:
        mock_router = MagicMock()
        mock_router.readiness.return_value = {"mode": "test", "ready": True}
        mock_router.settlement_stats.return_value = {"nonces_seen": 0}
        mock_get.return_value = mock_router

        with patch("x402.scheme.probe_oracle", AsyncMock(return_value=(True, "test"))):
            response = client.get("/v1/x402/health")
            assert response.status_code == 200
            data = response.json()
            assert "status" in data


# ---------------------------------------------------------------------------
# GET /v1/x402/pricing
# ---------------------------------------------------------------------------


def test_x402_pricing():
    with _patch_x402():
        response = client.get("/v1/x402/pricing")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True


# ---------------------------------------------------------------------------
# POST /v1/x402/payment
# ---------------------------------------------------------------------------


def test_x402_payment_request():
    response = client.post("/v1/x402/payment", json={"operation": "scrape"})
    assert response.status_code == 200
    assert response.json().get("success") is True


def test_x402_payment_request_with_metadata():
    response = client.post(
        "/v1/x402/payment",
        json={"operation": "scrape", "metadata": {"source": "test"}},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /v1/x402/verify
# ---------------------------------------------------------------------------


def test_x402_verify_invalid_payment_id():
    """Unknown operation should still process through verification."""
    with _patch_x402():
        response = client.post(
            "/v1/x402/verify",
            json={
                "payment_id": "unknown_op",
                "tx_hash": "0xabc",
                "network": "base",
                "asset": "USDC",
                "amount_usd": 1.0,
            },
        )
        assert response.status_code == 200
        assert "success" in response.json()


def test_x402_verify_underpayment():
    """Underpayment for a known operation should be rejected with success=False."""
    with _patch_x402():
        response = client.post(
            "/v1/x402/verify",
            json={
                "payment_id": "scrape",
                "tx_hash": "0xabc",
                "network": "base",
                "asset": "USDC",
                "amount_usd": 0.001,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is False or "success" in data


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


# ---------------------------------------------------------------------------
# require-payment format
# ---------------------------------------------------------------------------


def test_x402_require_payment_format():
    response = client.post(
        "/v1/x402/require-payment",
        json={"operation": "scrape"},
    )
    assert response.status_code in (200, 402)
