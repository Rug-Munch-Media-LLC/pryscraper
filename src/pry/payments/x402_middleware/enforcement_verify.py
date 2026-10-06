"""x402 payment verification helpers (split from enforcement.py).

Pure code move — no logic changes (audit E41 split).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import base64
import json
import logging
from typing import Any

from pry.payments.x402 import (
    attestation_signer_address,
    attested_max_amount_required,
    verify_payment_required_attestation,
)

logger = logging.getLogger(__name__)


def _decode_presented_payment_required(raw: Any) -> dict[str, Any] | None:
    """Decode a client-echoed payment-required body (audit #1 gate).

    The PAYMENT-SIGNATURE payload may carry the attested 402 body the client
    actually received (so a MITM that rewrote ``payToAddress``/amount/network
    in the challenge is caught at settle time). The field is OPTIONAL and
    accepted as a parsed dict, a raw JSON string, or the Base64
    ``PAYMENT-REQUIRED`` header value. Returns None when absent/unparseable.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        decoded = json.loads(text)
        return decoded if isinstance(decoded, dict) else None
    except (ValueError, TypeError) as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_decode_presented_payment_required"},
        )
    try:
        decoded = json.loads(base64.b64decode(text).decode())
        return decoded if isinstance(decoded, dict) else None
    except (ValueError, TypeError, OSError) as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_decode_presented_payment_required"},
        )
        return None


def _verify_presented_attestation(payload: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """Verify the server attestation on a client-presented 402 body.

    Returns ``(ok, reason, body)`` for the audit #1 payTo-tamper gate:

    - ``(True, "", body)`` when the payload carries no ``payment_required``
      body or the body is UNATTESTED — backward compatible (a legacy body
      emitted with no server attestation key configured still passes).
      ``body`` is the decoded body (or ``{}`` when absent/unparseable-but-
      tolerated).
    - ``(False, reason, body)`` when the body IS attested but the signature
      does not validate against the server's own attestation signer (tampered
      payTo/amount/network) — FAIL CLOSED so a forged challenge can never
      steer a payment to an attacker-controlled address.
    """
    raw = payload.get("payment_required")
    if raw is None:
        return True, "", {}
    body = _decode_presented_payment_required(raw)
    if not isinstance(body, dict):
        logger.warning("x402_attestation_undecodable_body", extra={"field": "payment_required"})
        return False, "echoed payment-required body could not be decoded", {}
    if not isinstance(body.get("attestation"), dict):
        # Unattested challenge (no key configured at issue time) — legacy path.
        return True, "", body
    expected = attestation_signer_address()
    if not expected:
        # We have no attestation key, so we can never have issued an attested
        # body. A presented one is forged or from a different server.
        return False, "attested body presented but no local attestation key configured", body
    result = verify_payment_required_attestation(body, expected_signer=expected)
    if result.get("verified"):
        return True, "", body
    return False, str(result.get("reason") or "invalid attestation"), body


def _attested_required_atomic(
    body: dict[str, Any],
    network: str,
    asset: str,
) -> int:
    """Price binding (audit #7): the SIGNED required amount for this payment.

    Given an ALREADY-VERIFIED attested payment-required body, extract the
    ``maxAmountRequired`` (atomic) of the accept matching (network, asset).
    Returns 0 when the body is unattested (legacy path — no binding, the
    live-quote comparison applies) or no accept matches, so callers fall
    back to the previous behavior. The attestation itself was verified by
    :func:`_verify_presented_attestation` before this is consulted.
    """
    if not isinstance(body, dict) or not isinstance(body.get("attestation"), dict):
        return 0
    return attested_max_amount_required(body, network, asset)
