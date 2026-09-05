# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""x402 payment verification + settlement for hosting invoices.

Flow: attach proof → verify via the self-facilitator → settle on-chain
(funds only move on settlement success) → credit the prepaid ledger →
provision the :class:`HostedInstance` (or extend its expiry for a renewal)
→ mint an API key (signup only).

The self-facilitator hook (``_get_self_facilitator``) and the wallet
constants are resolved through the hosting package namespace so tests can
monkeypatch ``hosting._get_self_facilitator`` / ``hosting.X402_WALLET``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pry.commerce.hosting as _hosting
from pry.commerce import billing_service
from pry.commerce.hosting.email_verify import _email_gate_enabled
from pry.commerce.hosting.errors import Underpayment
from pry.commerce.hosting.persistence import (
    _load_invoice,
    _now,
    _parse_iso,
    _set_invoice_fields,
    _utc_iso,
)
from pry.commerce.hosting.provisioning import (
    _extend_instance,
    _instance_payload,
    _provision_instance,
)
from pry.commerce.hosting.signup import submit_hosting_payment
from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK
from pry.payments.x402.self_facilitator import SelfFacilitator

logger = logging.getLogger("pry.commerce.hosting")


# ── Verification + settlement ───────────────────────────────────────────────
async def _verify_x402_async(invoice: dict[str, Any], *, expired: bool) -> dict[str, Any]:
    """Verify the invoice's reported tx via the self-facilitator."""
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
    verification = await _hosting._get_self_facilitator().verify(
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
        return {
            "paid": True,
            "tx_hash": str(tx_hash),
            "confirmed_at": _utc_iso(_now()),
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


def _get_self_facilitator() -> SelfFacilitator:
    """Build the self-facilitator for hosting verification.

    Overridable in tests: monkeypatch ``hosting._get_self_facilitator`` to
    return a fake exposing ``async verify`` / ``async settle``.
    """
    return SelfFacilitator(pay_to=_hosting.X402_WALLET)


async def _settle_onchain_async(payment: dict[str, Any]) -> str | None:
    """Broadcast settlement via the self-facilitator. Returns tx hash or None."""
    return await _hosting._get_self_facilitator().settle(payment)


async def confirm_hosting_payment(
    invoice_id: str,
    payment_proof: str,
    *,
    network: str = "",
    asset: str = "",
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify + settle the x402 payment, then provision the hosted instance.

    ``payment_proof`` is the on-chain tx hash (plus optional EIP-3009
    ``authorization``). Flow: attach proof → verify via the self-facilitator
    → settle on-chain (funds only move on settlement success) → credit the
    prepaid ledger → provision the :class:`HostedInstance` (or extend its
    expiry for a renewal invoice) → mint an API key (signup only).

    Returns ``{paid, invoice_id, instance, api_key, tx_hash, reference}``.
    Raises ``ValueError`` for unknown invoices; a reported-but-unverified tx
    raises :class:`Underpayment` (never credited, never provisioned).
    """
    if not payment_proof or not payment_proof.strip():
        raise ValueError("payment_proof must be a non-empty transaction hash")
    invoice = _load_invoice(invoice_id)
    if invoice is None:
        raise ValueError(f"unknown hosting invoice {invoice_id!r}")
    plan_tier = str(invoice["plan_tier"])
    kind = str(invoice.get("kind", "signup"))
    user_id = str(invoice.get("user_id") or "")
    instance_id = str(invoice.get("instance_id") or "")
    amount_usd = float(invoice["amount_usd"])
    try:
        expires_at = _parse_iso(str(invoice["expires_at"]))
    except ValueError:
        expires_at = _now()
    expired = _now() >= expires_at

    # Email-verification gate (audit item #4): the portal is keyed by
    # user_email + instance id, so an unverified signup email must never
    # reach provisioning — otherwise a bad actor could sign up with someone
    # else's email and control the portal/receipt after paying. Fail closed
    # with an actionable reason. Renewal invoices are bound to an already
    # provisioned (hence verified) instance and skip the gate. [REVIEW]
    if kind == "signup" and not invoice.get("email_verified") and _email_gate_enabled():
        return {
            "paid": False,
            "invoice_id": invoice_id,
            "instance": None,
            "api_key": None,
            "reason": "email not verified — check your inbox for the verification link",
        }

    submit_hosting_payment(
        invoice_id, payment_proof, network=network, asset=asset, authorization=authorization
    )
    invoice = _load_invoice(invoice_id) or invoice
    result = await _verify_x402_async(invoice, expired=expired)
    if not result["paid"]:
        if result.get("tx_hash"):
            raise Underpayment(
                f"hosting payment not verified: {result.get('reason', 'unverified')}",
                reason=result.get("reason", "unverified"),
            )
        return {
            "paid": False,
            "invoice_id": invoice_id,
            "instance": None,
            "api_key": None,
            "reason": result.get("reason", "no payment reported"),
        }

    # ── On-chain settlement (funds move only here) ──
    payment = dict(invoice.get("payment") or {})
    settle_tx = await _settle_onchain_async(
        {
            "payment_id": invoice_id,
            "tx_hash": str(result["tx_hash"]),
            "network": str(payment.get("network") or X402_DEFAULT_NETWORK),
            "asset": str(payment.get("asset") or X402_DEFAULT_ASSET),
            "amount_usd": amount_usd,
            "authorization": payment.get("authorization"),
        }
    )
    if settle_tx is None:
        return {
            "paid": False,
            "invoice_id": invoice_id,
            "instance": None,
            "api_key": None,
            "reason": "settlement failed",
            "tx_hash": result["tx_hash"],
        }

    reference = f"hosting:{invoice_id}:{settle_tx}"
    already_credited = (invoice.get("credited_reference") or "") == reference
    if not already_credited:
        billing_service.credit(user_id, amount_usd, reason="deposit", reference=reference)
        _set_invoice_fields(invoice_id, credited_reference=reference)
    # Funds settled — the invoice is now paid.
    _set_invoice_fields(invoice_id, status="paid")

    if already_credited and instance_id:
        # Idempotent replay: the same proof already settled + provisioned.
        # Return the existing instance without re-crediting or re-provisioning.
        instance = _instance_payload(instance_id)
        api_key = None
    elif kind == "renewal" and instance_id:
        instance = _extend_instance(instance_id, months=1)
        api_key = None
    else:
        instance, api_key = _provision_instance(user_id, plan_tier)
        _set_invoice_fields(invoice_id, instance_id=instance["instance_id"])

    logger.info(
        "hosting_payment_confirmed",
        extra={
            "invoice_id": invoice_id,
            "kind": kind,
            "instance_id": instance["instance_id"] if instance else None,
            "user_id": user_id,
        },
    )

    # Human receipt: email the customer (never fails the provisioning flow).
    try:
        from pry.commerce.hosting.checkout import send_hosting_receipt

        user_email = str(invoice.get("user_email") or "")
        if user_email:
            send_hosting_receipt(
                to_email=user_email,
                invoice_id=invoice_id,
                plan_tier=plan_tier,
                amount_usd=amount_usd,
                tx_hash=str(settle_tx),
                api_key=api_key,
                instance_id=instance["instance_id"] if instance else None,
            )
    except Exception as e:  # noqa: BLE001 — receipt is best-effort
        logger.warning("hosting_receipt_error", extra={"error": str(e)[:120]})

    return {
        "paid": True,
        "invoice_id": invoice_id,
        "instance": instance,
        "api_key": api_key,  # plaintext, shown exactly once (signup only)
        "tx_hash": str(settle_tx),
        "reference": reference,
    }


def confirm_hosting_payment_sync(
    invoice_id: str,
    payment_proof: str,
    *,
    network: str = "",
    asset: str = "",
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sync bridge for :func:`confirm_hosting_payment` (``asyncio.run``).

    For CLI / tests / sync contexts. Use the async variant from a running
    event loop (FastAPI routes).
    """
    return asyncio.run(
        confirm_hosting_payment(
            invoice_id,
            payment_proof,
            network=network,
            asset=asset,
            authorization=authorization,
        )
    )
