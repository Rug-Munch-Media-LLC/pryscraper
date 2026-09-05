"""Pry — pack purchase confirmation (verify → settle → credit).

Public confirm surface for pack purchases. ``confirm_pack_purchase`` is the
SYNC API (``asyncio.run`` bridge, mirroring ``billing.subscription``) — good
for CLI / tests / sync routes. ``confirm_pack_purchase_async`` is the ASYNC
variant for FastAPI routes and other running event loops. Both share the
settlement core in :mod:`pry.commerce.billing.settlement`.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pry.commerce import billing_service
from pry.commerce.billing.accounts import _bind_account
from pry.commerce.billing.catalog import Underpayment, _pack_amount_atomic
from pry.commerce.billing.settlement import _settle_pack_purchase, _settle_pack_purchase_async
from pry.commerce.billing.store import ensure_loaded, invoices, lock, save_state_locked
from pry.commerce.billing.verify import verify_pack_payment, verify_pack_payment_async


def confirm_pack_purchase(
    invoice_id: str,
    tx_hash: str,
    network: str = "",
    asset: str = "",
    *,
    user_id: str = "",
    api_key: str = "",
    mint_key: bool = True,
) -> dict[str, Any]:
    """Verify a pack payment and, when verified, credit the balance.

    SYNC public API (``asyncio.run`` bridge) for CLI / tests / sync contexts.
    Use :func:`confirm_pack_purchase_async` from a running event loop.

    1. Attach ``tx_hash`` via ``submit_pack_payment``.
    2. Verify via the self-facilitator.
    3. When verified: credit the pack's USD value to the ledger (reason=
       ``deposit``, reference=``pack:<invoice_id>:<tx_hash>``), mint an API
       key on first purchase (crypto signup — no email), mark paid.
    4. Returns ``{paid, credits, amount_usd, amount_atomic, api_key, balance,
       user_id, tx_hash, reference}``.

    Raises :class:`Underpayment` when a tx is reported but does not verify —
    the caller surfaces this as a rejected payment, never a credit.
    """
    if not tx_hash or not tx_hash.strip():
        raise ValueError("tx_hash must be a non-empty transaction hash")
    ensure_loaded()
    with lock:
        invoice = invoices.get(invoice_id)
        if invoice is None:
            raise ValueError(f"unknown pack invoice {invoice_id!r}")
        _bind_account(invoice, user_id=user_id, api_key=api_key)
        account_user_id = invoice.get("user_id") or ""
        account_api_key = invoice.get("api_key") or ""
        amount_usd = invoice["amount_usd"]
        pack_id = invoice["pack_id"]
    save_state_locked()

    _attach_tx(invoice_id, tx_hash, network, asset)
    result = verify_pack_payment(invoice_id)
    if not result["paid"]:
        if result.get("tx_hash"):
            raise Underpayment(
                f"pack payment not verified: {result.get('reason', 'unverified')}",
                reason=result.get("reason", "unverified"),
            )
        return {
            "paid": False,
            "credits": 0,
            "amount_usd": amount_usd,
            "amount_atomic": _pack_amount_atomic(pack_id),
            "api_key": account_api_key,
            "balance": billing_service.get_balance(account_user_id),
            "reason": result.get("reason", "no payment reported"),
        }

    return _settle_pack_purchase(
        invoice_id,
        pack_id,
        user_id=account_user_id,
        api_key=account_api_key,
        tx_hash=str(result["tx_hash"]),
        paid_result=result,
        mint_key=mint_key,
    )


async def confirm_pack_purchase_async(
    invoice_id: str,
    tx_hash: str,
    network: str = "",
    asset: str = "",
    *,
    user_id: str = "",
    api_key: str = "",
    mint_key: bool = True,
) -> dict[str, Any]:
    """Async :func:`confirm_pack_purchase` (safe inside a running event loop).

    Verifies with ``await`` (no ``asyncio.run``), then settles via the shared
    settlement core. Identical contract to the sync variant.
    """
    if not tx_hash or not tx_hash.strip():
        raise ValueError("tx_hash must be a non-empty transaction hash")
    ensure_loaded()
    with lock:
        invoice = invoices.get(invoice_id)
        if invoice is None:
            raise ValueError(f"unknown pack invoice {invoice_id!r}")
        _bind_account(invoice, user_id=user_id, api_key=api_key)
        account_user_id = invoice.get("user_id") or ""
        account_api_key = invoice.get("api_key") or ""
        amount_usd = invoice["amount_usd"]
        pack_id = invoice["pack_id"]
    save_state_locked()

    _attach_tx(invoice_id, tx_hash, network, asset)
    result = await verify_pack_payment_async(invoice_id)
    if not result["paid"]:
        if result.get("tx_hash"):
            raise Underpayment(
                f"pack payment not verified: {result.get('reason', 'unverified')}",
                reason=result.get("reason", "unverified"),
            )
        return {
            "paid": False,
            "credits": 0,
            "amount_usd": amount_usd,
            "amount_atomic": _pack_amount_atomic(pack_id),
            "api_key": account_api_key,
            "balance": billing_service.get_balance(account_user_id),
            "reason": result.get("reason", "no payment reported"),
        }

    return await _settle_pack_purchase_async(
        invoice_id,
        pack_id,
        user_id=account_user_id,
        api_key=account_api_key,
        tx_hash=str(result["tx_hash"]),
        paid_result=result,
        mint_key=mint_key,
    )


def _attach_tx(invoice_id: str, tx_hash: str, network: str, asset: str) -> None:
    """Attach a reported tx to the invoice if not already recorded."""
    from pry.commerce.billing.packs import submit_pack_payment

    with lock:
        invoice = invoices.get(invoice_id)
    if invoice is None:
        return
    payment = invoice.get("payment", {})
    if payment.get("tx_hash") != tx_hash.strip() or network or asset:
        submit_pack_payment(invoice_id, tx_hash, network=network, asset=asset)
