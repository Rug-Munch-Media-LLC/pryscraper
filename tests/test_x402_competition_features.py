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


# ---------------------------------------------------------------------------
# 6-point lifecycle hooks + Retry-After
# ---------------------------------------------------------------------------


class _RetryAfterError(Exception):
    """Exception carrying an httpx-style response with a Retry-After header."""

    def __init__(self, retry_after: str):
        super().__init__("rate limited")
        self.response = type("R", (), {"headers": {"Retry-After": retry_after}})()


@pytest.fixture
def hook_handler(tmp_path: Path) -> X402Handler:
    """Handler with a mocked facilitator router (hooks NOT mocked)."""
    with (
        patch("pry.payments.x402.handler.FacilitatorRouter"),
        patch("pry.payments.x402.handler.get_facilitator_router"),
    ):
        h = X402Handler(
            payments_file=tmp_path / "payments.jsonl",
            settlements_file=tmp_path / "settlements.jsonl",
        )
        h.router = AsyncMock()
        yield h


@pytest.mark.asyncio
async def test_pre_verify_hook_aborts(hook_handler: X402Handler):
    """A pre-verify hook returning {"abort": True} blocks verification."""
    hook_handler.on_pre_verify(lambda **kw: {"abort": True, "reason": "blocked"})
    result = await hook_handler.verify_payment(payment_id="p1", tx_hash="0xabc", amount_usd=1.0)
    assert result["verified"] is False
    assert result["reason"] == "blocked"
    hook_handler.router.verify.assert_not_called()


@pytest.mark.asyncio
async def test_post_verify_hook_fires(hook_handler: X402Handler):
    """A post-verify hook fires after successful verification."""
    hook_handler.router.verify = AsyncMock(return_value={"verified": True})
    fired = []
    hook_handler.on_post_verify(lambda record: fired.append(record))
    await hook_handler.verify_payment(payment_id="p1", tx_hash="0xabc", amount_usd=1.0)
    assert len(fired) == 1
    assert fired[0]["payment_id"] == "p1"
    assert fired[0]["verified"] is True


@pytest.mark.asyncio
async def test_on_verify_failure_hook_fires(hook_handler: X402Handler):
    """An on-verify-failure hook fires when the router rejects the payment."""
    hook_handler.router.verify = AsyncMock(return_value={"verified": False, "reason": "bad"})
    fired = []
    hook_handler.on_verify_failure(lambda **kw: fired.append(kw))
    result = await hook_handler.verify_payment(payment_id="p1", tx_hash="0xabc", amount_usd=1.0)
    assert result["verified"] is False
    assert len(fired) == 1
    assert fired[0]["reason"] == "bad"


@pytest.mark.asyncio
async def test_pre_settle_hook_aborts(hook_handler: X402Handler):
    """A pre-settle hook returning {"abort": True} blocks settlement."""
    hook_handler.on_pre_settle(lambda **kw: {"abort": True, "reason": "nope"})
    result = await hook_handler.settle_payment(payment_id="p1", tx_hash="0xabc", amount_usd=1.0)
    assert result["success"] is False
    assert result["error"] == "nope"
    hook_handler.router.settle.assert_not_called()


@pytest.mark.asyncio
async def test_post_settle_hook_fires(hook_handler: X402Handler):
    """A post-settle hook fires after successful settlement."""
    hook_handler.router.settle = AsyncMock(return_value={"success": True})
    with patch("pry.payments.x402.handler.fire_settlement_webhook", new=AsyncMock()):
        fired = []
        hook_handler.on_post_settle(lambda record: fired.append(record))
        result = await hook_handler.settle_payment(payment_id="p1", tx_hash="0xabc", amount_usd=1.0)
    assert result["success"] is True
    assert len(fired) == 1
    assert fired[0]["payment_id"] == "p1"


@pytest.mark.asyncio
async def test_settle_retry_after_header_respected(hook_handler: X402Handler):
    """Retry-After from the facilitator error response overrides backoff delay."""
    hook_handler.router.settle = AsyncMock(side_effect=[_RetryAfterError("7"), {"success": True}])
    with (
        patch("pry.payments.x402.handler.asyncio.sleep", new=AsyncMock()) as mock_sleep,
        patch("pry.payments.x402.handler.fire_settlement_webhook", new=AsyncMock()),
    ):
        result = await hook_handler.settle_payment(payment_id="p1", tx_hash="0xabc", amount_usd=1.0)
    assert result["success"] is True
    mock_sleep.assert_awaited_once_with(7)
