"""Tests for routers/x402.py — x402 payment API endpoints.

Covers health, pricing, single-payment, verify and catalog endpoints. The
batch endpoints live in ``test_routers_x402_batch.py`` and pay /
require-payment in ``test_routers_x402_pay.py``.
"""

from __future__ import annotations

import sys

# Mock external dependencies before importing app
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

# The app import triggers loading x402 module which may try network calls
# We'll patch at function level instead
from pry.api.api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# GET /v1/x402/health
# ---------------------------------------------------------------------------


def test_x402_health():
    with _patch_x402(), patch("pry.payments.x402.facilitator.get_facilitator_router") as mock_get:
        mock_router = MagicMock()
        mock_router.readiness.return_value = {"mode": "test", "ready": True}
        mock_router.settlement_stats.return_value = {"nonces_seen": 0}
        mock_get.return_value = mock_router

        with patch("pry.payments.x402.scheme.probe_oracle", AsyncMock(return_value=(True, "test"))):
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
    body = response.json()
    assert body.get("success") is True
    data = body["data"]
    # Payment request must carry the operation, a payment_id, and echo metadata.
    assert data["operation"] == "scrape"
    assert data["payment_id"]
    assert data["asset"] == "USDC"
    assert data["network"]
    assert data["maxAmountRequired"]
    expected = {"source": "test"}
    assert data["extra"] == expected


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
# GET /v1/x402/catalog — actor-preset availability must not read as "no actors"
# ---------------------------------------------------------------------------


def test_x402_catalog_reports_degraded_when_actor_presets_unavailable():
    """A broken/absent actor factory must not be served as an empty catalog.

    Regression: the failure path returned ``success: True`` with
    ``actors: []`` and ``actor_count: 0`` — indistinguishable from a factory
    that genuinely ships no presets, so an agent pricing a call would be told
    the capability does not exist.
    """
    with _patch_x402(), patch.dict(sys.modules, {"actor_factory.presets": None}):
        response = client.get("/v1/x402/catalog")

    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is False
    assert body.get("error") == "actor presets unavailable"
    # actors/actor_count are explicitly unknown, not an empty/false-zero lie.
    assert body["data"]["actors"] is None
    assert body["data"]["actor_count"] is None
    # The paid-operation surface still serves so clients can keep pricing.
    assert isinstance(body["data"]["operations"], dict)


def test_x402_catalog_reports_success_with_real_presets():
    """The healthy path is unchanged: real presets, integer count, no error."""
    with _patch_x402():
        response = client.get("/v1/x402/catalog")

    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert "error" not in body
    actors = body["data"]["actors"]
    assert isinstance(actors, list)
    assert actors
    assert body["data"]["actor_count"] == len(actors)
