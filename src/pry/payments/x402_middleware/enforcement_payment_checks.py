"""Pure payment-signature checks for the x402 gate.

Decode, attestation (audit #1), price-binding (audit #7) and settle-result
predicates. No I/O — orchestration stays in ``enforcement_payment``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import base64
import json
import logging
from typing import Any

from pry.core.audit import audit_event
from pry.payments.x402 import validate_client_amount
from pry.payments.x402_middleware.enforcement_verify import (
    _attested_required_atomic,
    _verify_presented_attestation,
)

logger = logging.getLogger(__name__)


def _parse_payment_signature(
    payment_sig: str, default_network: str
) -> tuple[str, str, str, str, float] | None:
    """Decode a PAYMENT-SIGNATURE header, or None on decode error.

    Returns ``(payment_id, tx_hash, network, asset, amount_usd)``.
    """
    try:
        payload = json.loads(base64.b64decode(payment_sig).decode())
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("x402_payment_decode_failed", extra={"error": str(exc)})
        return None
    payment_id = payload.get("payment_id", "")
    tx_hash = payload.get("tx_hash", "") or payload.get("payload", "")
    return (
        payment_id,
        tx_hash,
        payload.get("network", default_network),
        payload.get("asset", ""),
        float(payload.get("amount_usd", 0.0)),
    )


def _attestation_rejected(
    payload: dict[str, Any],
    caller_key: str,
    path: str,
    operation: str,
    payment_id: str,
) -> tuple[bool, Any]:
    """Audit #1 presented-attestation gate; returns ``(ok, attested_body)``."""
    ok, reason, body = _verify_presented_attestation(payload)
    if ok:
        return True, body
    audit_event(
        "x402_attestation_rejected",
        actor=caller_key,
        path=path,
        operation=operation,
        payment_id=payment_id,
        reason=reason,
    )
    logger.warning(
        "x402_attestation_failed",
        extra={
            "operation": operation,
            "path": path,
            "payment_id": payment_id,
            "reason": reason,
        },
    )
    return False, body


def _price_bound(
    operation: str,
    amount_usd: float,
    asset: str,
    network: str,
    caller_key: str,
    path: str,
) -> bool:
    """Server-side price binding (audit #7); True when acceptable."""
    ok, price_reason = validate_client_amount(operation, amount_usd, asset, network=network)
    if ok:
        return True
    audit_event(
        "x402_underpayment_rejected",
        actor=caller_key,
        path=path,
        operation=operation,
        reason=price_reason,
    )
    logger.warning(
        "x402_underpayment_rejected",
        extra={"operation": operation, "path": path, "reason": price_reason},
    )
    return False


def _attested_atomic_for(attested_body: Any, network: str, asset: str) -> int | None:
    """Signed maxAmountRequired for the volatile-asset compare, when attested."""
    return _attested_required_atomic(attested_body, network, asset)


def _settle_failed(settlement: dict[str, Any] | None) -> bool:
    """True when settlement is missing or did not report success."""
    return not settlement or settlement.get("success") is not True


def _log_settle_denied(
    caller_key: str,
    path: str,
    payment_id: str,
    tx_hash: str,
    settlement: dict[str, Any] | None,
) -> None:
    """Audit + warn a verify-passed / settle-failed access denial (fix #3)."""
    reason = settlement.get("reason", "") if settlement else ""
    audit_event(
        "x402_settle_failed_access_denied",
        actor=caller_key,
        path=path,
        payment_id=payment_id,
        reason=reason,
    )
    logger.warning(
        "x402_settle_failed_access_denied",
        extra={"payment_id": payment_id, "tx_hash": tx_hash, "reason": reason},
    )
