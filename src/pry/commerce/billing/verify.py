"""Pry — pack payment verification via the x402 self-facilitator.

Checks the on-chain payment reported for a pack invoice. An invoice with no
reported tx is unpaid; expired invoices fail closed unless the payment
verifies. The facilitator is resolved through the packs facade so tests can
monkeypatch ``billing.packs._get_self_facilitator``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
from typing import Any

from pry.commerce.billing.clock import now, parse_iso, utc_iso
from pry.commerce.billing.store import ensure_loaded, invoices, lock, save_state_locked
from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK


def _facilitator() -> Any:
    """Resolve the self-facilitator via the packs facade (test-overridable)."""
    import pry.commerce.billing.packs as packs

    return packs._get_self_facilitator()


def verify_pack_payment(invoice_id: str) -> dict[str, Any]:
    """Check the on-chain payment for a pack invoice via the self-facilitator.

    Returns ``{paid: bool, tx_hash, confirmed_at, reason, status, signer?}``.
    An invoice with no reported tx is unpaid. Expired invoices fail closed
    unless the payment verifies.
    """
    ensure_loaded()
    with lock:
        invoice = invoices.get(invoice_id)
    if invoice is None:
        return {"paid": False, "tx_hash": None, "confirmed_at": None, "reason": "unknown invoice"}
    current = now()
    try:
        expires_at = parse_iso(str(invoice["expires_at"]))
    except ValueError:
        expires_at = current  # malformed persistence → fail closed
    expired = current >= expires_at
    return asyncio.run(_verify_x402_async(invoice, expired=expired))


async def verify_pack_payment_async(invoice_id: str) -> dict[str, Any]:
    """Async :func:`verify_pack_payment` (safe inside a running event loop)."""
    ensure_loaded()
    with lock:
        invoice = invoices.get(invoice_id)
    if invoice is None:
        return {"paid": False, "tx_hash": None, "confirmed_at": None, "reason": "unknown invoice"}
    current = now()
    try:
        expires_at = parse_iso(str(invoice["expires_at"]))
    except ValueError:
        expires_at = current
    expired = current >= expires_at
    return await _verify_x402_async(invoice, expired=expired)


async def _verify_x402_async(invoice: dict[str, Any], *, expired: bool) -> dict[str, Any]:
    """Shared async verify core used by both sync and async entry points."""
    payment = invoice["payment"]
    tx_hash = payment.get("tx_hash")
    if tx_hash is None:
        if expired:
            return {
                "paid": False,
                "tx_hash": None,
                "confirmed_at": None,
                "reason": "expired",
                "status": "expired",
            }
        return {
            "paid": False,
            "tx_hash": None,
            "confirmed_at": None,
            "reason": "no payment reported for invoice",
            "status": invoice.get("status", "pending"),
        }

    verification = await _facilitator().verify(
        {
            "payment_id": invoice["invoice_id"],
            "tx_hash": str(tx_hash),
            "network": str(payment.get("network") or X402_DEFAULT_NETWORK),
            "asset": str(payment.get("asset") or X402_DEFAULT_ASSET),
            "amount_usd": float(payment.get("amount_usd") or 0.0),
            "authorization": payment.get("authorization"),
        }
    )
    if verification.verified and not expired:
        with lock:
            invoice["status"] = "paid"
            save_state_locked()
        return {
            "paid": True,
            "tx_hash": str(tx_hash),
            "confirmed_at": utc_iso(now()),
            "reason": "",
            "status": "paid",
            "signer": verification.signer,
        }
    reason = verification.reason or ("expired" if expired else "not verified")
    return {
        "paid": False,
        "tx_hash": str(tx_hash),
        "confirmed_at": None,
        "reason": reason,
        "status": "expired" if expired else invoice.get("status", "pending"),
    }
