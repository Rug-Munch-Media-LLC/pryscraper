"""Tests for x402 competition features: scheme negotiation, extension policy,
typed errors, and the authorize/capture/void payment flow."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pry.payments.x402.handler import SettleError, VerifyError, X402Handler
from pry.payments.x402.scheme import negotiate_scheme, validate_scheme_extension

# ---------------------------------------------------------------------------
# negotiate_scheme
# ---------------------------------------------------------------------------


def test_negotiate_scheme_exact_default():
    """No client schemes → default to 'exact'."""
    assert negotiate_scheme(None) == "exact"
    assert negotiate_scheme([]) == "exact"


def test_negotiate_scheme_native_match():
    """Client supports the network-native scheme on eip155 → 'exact'."""
    assert negotiate_scheme(["exact"], network="eip155:8453") == "exact"


def test_negotiate_scheme_fallback():
    """Client only supports an unknown scheme → fall back to it."""
    assert negotiate_scheme(["custom"]) == "custom"


# ---------------------------------------------------------------------------
# validate_scheme_extension
# ---------------------------------------------------------------------------


def _baseline() -> dict:
    return {
        "scheme": "exact",
        "network": "base",
        "asset": "USDC",
        "max_timeout_seconds": 60,
        "accepts": [{"scheme": "exact", "network": "base"}],
        "extra": {"paymentFlow": "escrow"},
    }


def test_validate_scheme_extension_ok():
    """Enriched payload identical to baseline → no error."""
    assert validate_scheme_extension(_baseline(), _baseline(), "test-ext") is None


def test_validate_scheme_extension_rejects_field_change():
    """Changing an immutable field (network) → error string."""
    enriched = _baseline()
    enriched["network"] = "optimism"
    err = validate_scheme_extension(_baseline(), enriched, "test-ext")
    assert err is not None
    assert "network" in err


def test_validate_scheme_extension_rejects_accepts_length():
    """Different accepts length → error string."""
    enriched = _baseline()
    enriched["accepts"] = enriched["accepts"] + [{"scheme": "exact"}]
    err = validate_scheme_extension(_baseline(), enriched, "test-ext")
    assert err is not None
    assert "accepts length" in err


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


def test_verify_error_class():
    err = VerifyError("test")
    assert err.reason == "test"
    assert str(err) == "test"


def test_settle_error_class():
    err = SettleError("test")
    assert err.reason == "test"
    assert str(err) == "test"


# ---------------------------------------------------------------------------
# authorize → capture → void flow
# ---------------------------------------------------------------------------


@pytest.fixture
def handler(tmp_path: Path) -> X402Handler:
    """Handler with mocked facilitator and mocked verify_payment."""
    with (
        patch("pry.payments.x402.handler.FacilitatorRouter"),
        patch("pry.payments.x402.handler.get_facilitator_router"),
    ):
        h = X402Handler(
            payments_file=tmp_path / "payments.jsonl",
            settlements_file=tmp_path / "settlements.jsonl",
        )
        h.verify_payment = AsyncMock(return_value={"verified": True, "payment_id": "p1"})
        yield h


@pytest.mark.asyncio
async def test_handler_authorize_capture_void(handler: X402Handler):
    """authorize → capture succeeds; authorize → void also succeeds."""
    auth = await handler.authorize_payment(
        payment_id="p1",
        tx_hash="0xabc",
        network="base",
        asset="USDC",
        amount_usd=1.0,
    )
    assert auth == {"authorized": True, "payment_id": "p1", "captured": False}

    capture = handler.capture_payment("p1")
    assert capture == {"success": True, "payment_id": "p1", "captured": True}

    # Re-authorize then void
    await handler.authorize_payment(payment_id="p2", tx_hash="0xdef", network="base", asset="USDC")
    void = handler.void_payment("p2")
    assert void == {"success": True, "payment_id": "p2", "voided": True}
    # Voided payment cannot be captured
    assert handler.capture_payment("p2") == {
        "success": False,
        "error": "no authorization found",
    }
