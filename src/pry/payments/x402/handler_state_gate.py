"""Pry — X402Handler payment gate + stats (``StateMixin`` slice).

``is_paid`` is the access gate: verified, unexpired, caller-bound, and (when an
operation is supplied) bought for that operation at a price the recorded atomic
amount still covers. Every malformed/unknown input fails closed.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

from pry.payments.x402 import (
    PAYMENT_VALIDITY_SECONDS,
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    X402_OFFLINE_MODE,
    X402_SELF_FACILITATE,
)
from pry.payments.x402.scheme import (
    SUPPORTED_ASSETS,
    SUPPORTED_NETWORKS,
    VERIFICATION_STATUS,
    X402_PRICING,
    X402Asset,
    X402Network,
    X402Scheme,
    asset_to_atomic,
    network_verification_status,
    resolve_price_usd,
)

logger = logging.getLogger("pry.payments.x402.handler")


def _warn_swallowed(exc: Exception, handler: str) -> None:
    logger.warning(
        "payments_exception_swallowed",
        extra={"error": str(exc), "handler": handler},
    )


def _expiry_ok(payment: dict[str, Any], now: datetime) -> bool:
    """True only for a well-formed, still-valid ``expires_at`` (else fail closed)."""
    expires_at = payment.get("expires_at")
    if not expires_at:
        return False  # no expiry recorded → treat as expired (fail closed)
    try:
        return datetime.fromisoformat(expires_at) > now
    except ValueError as exc:
        _warn_swallowed(exc, "StateMixin.is_paid")
        return False  # malformed expiry → fail closed


def _caller_ok(payment: dict[str, Any], caller_key: str) -> bool:
    """A caller-bound payment is reusable only by the caller it was bound to."""
    stored_caller = payment.get("caller_key") or ""
    return not stored_caller or (bool(caller_key) and stored_caller == caller_key)


def _amount_covers(payment: dict[str, Any], operation: str) -> bool:
    """Server-authoritative atomic recheck for a gated operation."""
    asset = payment.get("asset") or X402_DEFAULT_ASSET
    network = payment.get("network") or X402_DEFAULT_NETWORK
    required = resolve_price_usd(operation, network=network, asset=asset)
    if required <= 0 or not math.isfinite(float(required)):
        return False  # no authoritative price → fail closed
    try:
        required_atomic = asset_to_atomic(required, asset, network)
    except (TypeError, ValueError) as exc:
        _warn_swallowed(exc, "StateMixin._amount_covers")
        return False  # unquoteable price → fail closed
    raw_paid = payment.get("required_amount_atomic")
    if raw_paid is None:
        return False  # pre-hardening record without atomics → fail closed
    try:
        paid_atomic = int(raw_paid)
    except (TypeError, ValueError) as exc:
        _warn_swallowed(exc, "StateMixin._amount_covers")
        return False  # garbled atomics → fail closed
    return paid_atomic >= required_atomic


class GateMixin:
    """Payment access gate, atomic recheck and public stats."""

    payments: list[dict[str, Any]]
    wallet: str
    facilitator_url: str

    def is_paid(self, payment_id: str, caller_key: str = "", operation: str = "") -> bool:
        """True only if the payment is verified, unexpired, caller-bound and
        still satisfies the gate for ``operation``.

        A gated operation also requires the payment to have been purchased for
        that exact operation and to still cover its CURRENT server price; a
        cheap payment can never unlock a pricier endpoint. Payments recorded
        before this hardening fail closed for gated operations.
        """
        now = datetime.now(UTC)
        self._ensure_loaded()
        for p in self.payments:
            if p.get("payment_id") != payment_id or not p.get("verified"):
                continue
            if not _expiry_ok(p, now) or not _caller_ok(p, caller_key):
                continue
            if operation and not _operation_covers(p, operation):
                continue
            return True
        return False

    def _amount_covers(self, payment: dict[str, Any], operation: str) -> bool:
        return _amount_covers(payment, operation)

    def get_stats(self) -> dict[str, Any]:
        self._ensure_loaded()
        return {
            "total_payments": len(self.payments),
            "wallet": self.wallet,
            "facilitator": self.facilitator_url,
            "pricing": X402_PRICING,
            "supported_networks": [n.value for n in X402Network],
            "supported_assets": [a.value for a in X402Asset],
            "supported_schemes": [s.value for s in X402Scheme],
            "networks": SUPPORTED_NETWORKS,
            "caip2_networks": list(SUPPORTED_ASSETS.keys()),
            "asset_table": SUPPORTED_ASSETS,
            "verification_status": VERIFICATION_STATUS,
            "verification_status_by_network": {
                network_id: network_verification_status(network_id)
                for network_id in SUPPORTED_ASSETS
            },
            "offline_mode": X402_OFFLINE_MODE,
            "self_hosted": X402_SELF_FACILITATE,
            "payment_validity_seconds": PAYMENT_VALIDITY_SECONDS,
            "default_network": X402_DEFAULT_NETWORK,
            "default_asset": X402_DEFAULT_ASSET,
        }


def _operation_covers(payment: dict[str, Any], operation: str) -> bool:
    """Cross-operation replay + underpayment rejection for a gated operation."""
    if (payment.get("operation") or "") != operation:
        return False
    return _amount_covers(payment, operation)
