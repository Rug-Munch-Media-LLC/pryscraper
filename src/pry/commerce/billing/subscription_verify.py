"""Pry — subscription payment verification + settlement.

Checks invoice payment status and settles verified x402 payments on-chain:
- **x402**: ``SelfFacilitator.verify`` ecrecovers the recorded tx; only
  ``SelfFacilitator.settle`` broadcasts it and moves the funds.
- **btcpay**: polls ``GET {url}/api/v1/stores/{store}/invoices/{id}``;
  ``paid`` is True when upstream status is ``Settled``.
Expired invoices fail closed (``paid=False``, ``reason="expired"``) unless the
backend reports settlement.
NOTES / REVIEW flags
- ``verify_subscription_payment`` is SYNC and runs the async verify via
  ``asyncio.run``; from inside a running event loop it raises ``RuntimeError``.
- ``_get_self_facilitator`` lives on the :mod:`…subscription` facade so tests
  can monkeypatch it (with ``_now``) there.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

import httpx

from pry.commerce.billing import subscription as _facade
from pry.commerce.billing.subscription_invoices import _btcpay_env, _extract_btcpay_tx_hash
from pry.commerce.billing.subscription_state import (
    _INVOICES,
    _ensure_loaded,
    _lock,
    _save_state_locked,
)
from pry.commerce.billing.subscription_time import _parse_iso, _utc_iso
from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK

if TYPE_CHECKING:
    from pry.payments.x402.self_facilitator import VerifyResult

logger = logging.getLogger(__name__)


# ── Verification ────────────────────────────────────────────────────────────
def verify_subscription_payment(invoice_id: str) -> dict[str, Any]:
    """Check the payment status of an invoice.

    Returns ``{paid: bool, tx_hash, confirmed_at, reason}``.

    - **x402**: verifies the recorded tx via the self-facilitator
      (``SelfFacilitator.verify``); an invoice with no reported tx is unpaid.
    - **btcpay**: polls ``GET {url}/api/v1/stores/{store}/invoices/{id}``;
      ``paid`` is True when upstream status is ``Settled``.

    Expired invoices fail closed (``paid=False``, ``reason="expired"``)
    regardless of backend, unless the backend reports settlement.
    """
    _ensure_loaded()
    with _lock:
        invoice = _INVOICES.get(invoice_id)
    if invoice is None:
        return {"paid": False, "tx_hash": None, "confirmed_at": None, "reason": "unknown invoice"}

    now = _facade._now()
    try:
        expires_at = _parse_iso(str(invoice["expires_at"]))
    except ValueError:
        logger.warning("subscription_verify_suppressed", exc_info=True)
        expires_at = now  # malformed persisted expiry → fail closed
    expired = now >= expires_at
    if invoice.get("payment_method") == "btcpay":
        return _verify_btcpay(invoice, expired=expired)
    return _verify_x402(invoice, expired=expired)


def _verify_x402(invoice: dict[str, Any], *, expired: bool) -> dict[str, Any]:
    """Verify an x402 invoice via the self-facilitator (or local state)."""
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

    verification = _verify_x402_payment_sync(
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
        with _lock:
            invoice["status"] = "paid"
            _save_state_locked()
        return {
            "paid": True,
            "tx_hash": str(tx_hash),
            "confirmed_at": _utc_iso(_facade._now()),
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


async def _verify_x402_payment(payment: dict[str, Any]) -> VerifyResult:
    """Async core: delegate verification to the self-facilitator."""
    return await _facade._get_self_facilitator().verify(payment)


def _verify_x402_payment_sync(payment: dict[str, Any]) -> VerifyResult:
    """Bridge the async self-facilitator into the sync public API."""
    return asyncio.run(_verify_x402_payment(payment))


async def _settle_x402_payment_async(payment: dict[str, Any]) -> str | None:
    """Async core: broadcast settlement via the self-facilitator."""
    return await _facade._get_self_facilitator().settle(payment)


def settle_subscription_payment(invoice_id: str) -> dict[str, Any]:
    """Settle a verified x402 subscription payment on-chain.

    Verify only ecrecovers the EIP-3009 authorization; funds move only when
    ``SelfFacilitator.settle`` broadcasts. Activate only when ``settled`` is
    True. Returns ``{settled, tx_hash, reason}``; idempotent.
    """
    _ensure_loaded()
    with _lock:
        invoice = _INVOICES.get(invoice_id)
    if invoice is None or invoice.get("payment_method") == "btcpay":
        return {"settled": False, "tx_hash": None, "reason": "not settlable"}
    payment = invoice.get("payment") or {}
    tx_hash = payment.get("tx_hash")
    if tx_hash is None:
        return {"settled": False, "tx_hash": None, "reason": "no payment reported"}
    settle_tx = asyncio.run(
        _settle_x402_payment_async(
            {
                "payment_id": invoice["invoice_id"],
                "tx_hash": str(tx_hash),
                "network": str(payment.get("network") or X402_DEFAULT_NETWORK),
                "asset": str(payment.get("asset") or X402_DEFAULT_ASSET),
                "amount_usd": float(payment.get("amount_usd") or 0.0),
                "authorization": payment.get("authorization"),
            }
        )
    )
    if settle_tx is None:
        return {"settled": False, "tx_hash": None, "reason": "settlement failed"}
    # Persist the instant funds moved; revenue attribution must use this time.
    settled_at = _utc_iso(_facade._now())
    with _lock:
        invoice["settled_at"] = settled_at
        invoice["settlement_tx_hash"] = str(settle_tx)
        _save_state_locked()
    return {"settled": True, "tx_hash": str(settle_tx), "reason": ""}


def _btcpay_outcome(settled: bool, expired: bool, status: str, tx_hash: str) -> dict[str, Any]:
    """Build the verifier result for a polled BTCPay invoice."""
    state = "paid" if settled else ("expired" if expired else status)
    return {
        "paid": settled,
        "tx_hash": tx_hash or None,
        "confirmed_at": _utc_iso(_facade._now()) if settled else None,
        "reason": "" if settled else ("expired" if expired else f"btcpay status {status}"),
        "status": state,
    }


def _verify_btcpay(invoice: dict[str, Any], *, expired: bool) -> dict[str, Any]:
    """Poll a BTCPay invoice for settlement status."""
    btcpay = _btcpay_env()
    if btcpay is None:
        return {
            "paid": False,
            "tx_hash": None,
            "confirmed_at": None,
            "reason": "btcpay unconfigured",
        }
    url, token, store = btcpay
    invoice_id = str(invoice["invoice_id"])
    try:
        response = httpx.get(
            f"{url}/api/v1/stores/{store}/invoices/{invoice_id}",
            headers={"Authorization": f"token {token}"},
            timeout=float(os.environ.get("PRY_BTCPAY_TIMEOUT", "15")),
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("subscription_verify_suppressed", exc_info=True)
        return {
            "paid": False,
            "tx_hash": None,
            "confirmed_at": None,
            "reason": f"btcpay lookup failed: {exc}",
        }

    status = str(data.get("status", "New")) if isinstance(data, dict) else "New"
    tx_hash = _extract_btcpay_tx_hash(data) if isinstance(data, dict) else ""
    # BTCPay's upstream status is authoritative: a "Settled" invoice counts as
    # paid even if our local TTL expired (BTCPay manages its own expiry).
    settled = status == "Settled"
    with _lock:
        if settled:
            invoice["status"] = "paid"
            # setdefault keeps the first observed settlement time (idempotent).
            invoice.setdefault("settled_at", _utc_iso(_facade._now()))
        if isinstance(data, dict):
            invoice.setdefault("btcpay", {})["upstream_status"] = status
        _save_state_locked()
    return _btcpay_outcome(settled, expired, status, tx_hash)
