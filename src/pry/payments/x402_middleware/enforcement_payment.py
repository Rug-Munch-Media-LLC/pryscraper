"""Payment orchestration for the x402 gate (verify + settle + serve).

Behavior-preserving refactor: drives the pure checks in
``enforcement_payment_checks`` and the facilitator via ``mw.handler``, then
serves the upstream response with the PAYMENT-RESPONSE receipt attached.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import base64
import json
import logging
from typing import Any

from pry.payments.x402_middleware.enforcement_payment_checks import (
    _attestation_rejected,
    _attested_atomic_for,
    _log_settle_denied,
    _parse_payment_signature,
    _price_bound,
    _settle_failed,
)

logger = logging.getLogger(__name__)


async def _verify_and_settle(
    mw: Any,
    parsed: tuple[str, str, str, str, float],
    operation: str,
    caller_key: str,
    attested_atomic: int | None,
) -> dict[str, Any] | None:
    """Facilitator verify then settle. Returns the settlement, or None.

    None means verify failed (the caller falls back to a fresh 402).
    """
    payment_id, tx_hash, network, asset, amount_usd = parsed
    verify_result = await mw.handler.verify_payment(
        payment_id,
        tx_hash,
        network=network,
        asset=asset,
        amount_usd=amount_usd,
        operation=operation,
        caller_key=caller_key,
        attested_required_atomic=attested_atomic,
    )
    if not verify_result.get("verified"):
        return None
    return await mw.handler.settle_payment(
        payment_id,
        tx_hash,
        network=network,
        asset=asset,
        amount_usd=amount_usd,
        operation=operation,
    )


async def _serve_settled(
    mw: Any,
    scope: dict[str, Any],
    receive: Any,
    send: Any,
    settlement: dict[str, Any],
    payment_id: str,
    tx_hash: str,
    caller_key: str,
    operation: str,
) -> None:
    """Attach the settlement receipt and serve the upstream response."""
    response_b64_bytes = base64.b64encode(json.dumps(settlement).encode()).decode().encode()
    scope["x402_verified"] = {
        "payment_id": payment_id,
        "caller": caller_key,
        "operation": operation,
        "tx_hash": tx_hash,
    }

    async def wrapped_send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            hdrs = list(message.get("headers", []))
            hdrs.append((b"payment-response", response_b64_bytes))
            message["headers"] = hdrs
        await send(message)

    await mw.app(scope, receive, wrapped_send)


async def _handle_presented_payment(
    mw: Any,
    payment_sig: str,
    operation: str,
    caller_key: str,
    path: str,
    scope: dict[str, Any],
    receive: Any,
    send: Any,
) -> bool:
    """Decode, attest, price-check, verify and settle a PAYMENT-SIGNATURE.

    Returns True when the request was passed through (or a failure 402 was
    already sent); False means no usable signature — the caller falls back
    to the fresh-402 path.
    """
    parsed = _parse_payment_signature(payment_sig, mw.network)
    if parsed is None:
        return False
    payment_id, tx_hash = parsed[0], parsed[1]
    if not (payment_id and tx_hash):
        return False
    try:
        payload = json.loads(base64.b64decode(payment_sig).decode())
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("x402_payment_decode_failed", extra={"error": str(exc)})
        return False
    attest_ok, attest_body = _attestation_rejected(payload, caller_key, path, operation, payment_id)
    if not attest_ok:
        await mw._send_payment_required(operation, path, send)
        return True
    network, asset, amount_usd = parsed[2], parsed[3], parsed[4]
    attested_atomic = _attested_atomic_for(attest_body, network, asset)
    if not _price_bound(operation, amount_usd, asset, network, caller_key, path):
        await mw._send_payment_required(operation, path, send)
        return True
    settlement = await _verify_and_settle(mw, parsed, operation, caller_key, attested_atomic)
    if settlement is None:
        return False
    if _settle_failed(settlement):
        _log_settle_denied(caller_key, path, payment_id, tx_hash, settlement)
        await mw._send_payment_required(operation, path, send)
        return True
    await _serve_settled(
        mw, scope, receive, send, settlement, payment_id, tx_hash, caller_key, operation
    )
    return True
