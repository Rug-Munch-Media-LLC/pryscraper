"""Pry — pack purchase settlement (on-chain settle → ledger credit → key mint).

Settlement gate: verify alone only ecrecovers the EIP-3009 authorization —
funds do not move until the self-facilitator broadcasts the settlement
(``SelfFacilitator.settle``). Credits are granted ONLY when settlement
succeeds; a failed broadcast returns a payment-failed result and the ledger
is never touched. Idempotent per tx via ``credited_reference``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
from typing import Any

from pry.commerce import billing_service
from pry.commerce.billing.accounts import _mint_key
from pry.commerce.billing.catalog import get_pack
from pry.commerce.billing.store import invoices, lock, save_state_locked
from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK


def _facilitator() -> Any:
    """Resolve the self-facilitator via the packs facade.

    Lazy import so tests can monkeypatch ``billing.packs._get_self_facilitator``
    and settlement picks it up at call time.
    """
    import pry.commerce.billing.packs as packs

    return packs._get_self_facilitator()


async def _settle_pack_purchase_async(
    invoice_id: str,
    pack_id: str,
    *,
    user_id: str,
    api_key: str,
    tx_hash: str,
    paid_result: dict[str, Any],
    mint_key: bool,
) -> dict[str, Any]:
    """Settle on-chain, then credit the ledger + mint a key. Idempotent per tx.

    Shared by the sync and async confirm paths. Never raises on the credit
    path; the callers guarantee ``paid_result["paid"]`` is True.
    """
    pack = get_pack(pack_id)
    reference = f"pack:{invoice_id}:{tx_hash}"

    # ── On-chain settlement (EIP-3009 transferFrom via the authorization) ──
    with lock:
        payment = dict(invoices[invoice_id].get("payment") or {})
    settle_tx = await _settle_onchain_async(
        {
            "payment_id": invoice_id,
            "tx_hash": str(tx_hash),
            "network": str(payment.get("network") or X402_DEFAULT_NETWORK),
            "asset": str(payment.get("asset") or X402_DEFAULT_ASSET),
            "amount_usd": float(payment.get("amount_usd") or 0.0),
            "authorization": payment.get("authorization"),
        }
    )
    if settle_tx is None:
        return {
            "paid": False,
            "credits": 0,
            "amount_usd": pack.price_usd,
            "amount_atomic": pack.amount_atomic,
            "api_key": api_key,
            "balance": billing_service.get_balance(user_id)["balance_usd"],
            "reason": "settlement failed",
            "tx_hash": tx_hash,
            "reference": reference,
        }

    with lock:
        stored_ref = invoices[invoice_id].get("credited_reference")
        already_credited = stored_ref == reference

    if already_credited:
        balance = billing_service.get_balance(user_id)
        credited = {"balance_usd": balance["balance_usd"]}
    else:
        credited = billing_service.credit(
            user_id, pack.price_usd, reason="deposit", reference=reference
        )
        with lock:
            invoices[invoice_id]["credited_reference"] = reference
            save_state_locked()

    resolved_key = api_key
    if mint_key and not resolved_key:
        issued = _mint_key(user_id, pack.id)
        resolved_key = issued["plaintext"]
        with lock:
            invoices[invoice_id]["api_key"] = resolved_key
            save_state_locked()

    return {
        "paid": True,
        "credits": pack.credits,
        "amount_usd": pack.price_usd,
        "amount_atomic": pack.amount_atomic,
        "api_key": resolved_key,
        "balance": credited["balance_usd"],
        "user_id": user_id,
        "tx_hash": tx_hash,
        "reference": reference,
    }


async def _settle_onchain_async(payment: dict[str, Any]) -> str | None:
    """Broadcast settlement via the self-facilitator. Returns tx hash or None."""
    return await _facilitator().settle(payment)


def _settle_pack_purchase(
    invoice_id: str,
    pack_id: str,
    *,
    user_id: str,
    api_key: str,
    tx_hash: str,
    paid_result: dict[str, Any],
    mint_key: bool,
) -> dict[str, Any]:
    """Sync bridge for :func:`_settle_pack_purchase_async` (``asyncio.run``)."""
    return asyncio.run(
        _settle_pack_purchase_async(
            invoice_id,
            pack_id,
            user_id=user_id,
            api_key=api_key,
            tx_hash=tx_hash,
            paid_result=paid_result,
            mint_key=mint_key,
        )
    )
