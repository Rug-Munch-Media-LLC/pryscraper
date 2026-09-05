"""Pry — bulk scrape-credit packs (crypto checkout via x402 self-facilitation).

Lets a user buy a BULK of scrape credits with USDC over Pry's own x402
self-facilitation rail (EIP-3009 on EVM / SPL on Solana) — no email, no
third-party processor, no KYC. The pack catalog carries server-authoritative
prices in atomic units; a verified payment is settled against the existing
prepaid USD ledger (:mod:`pry.commerce.billing_service`) and an API key is
minted on first purchase (crypto signup).

This module is the pack-checkout facade: invoice creation (x402
PaymentRequired manifest), payment submission, and the fail-closed wallet
gate. The flow is split across cohesive siblings:

- :mod:`pry.commerce.billing.catalog` — pack definitions + pricing
- :mod:`pry.commerce.billing.store` — invoice registry + JSON persistence
- :mod:`pry.commerce.billing.verify` — self-facilitator verification
- :mod:`pry.commerce.billing.settlement` — on-chain settle → ledger credit
- :mod:`pry.commerce.billing.confirm` — public confirm surface (sync/async)
- :mod:`pry.commerce.billing.accounts` — account binding, key mint, signup

The LEDGER remains USD-denominated — a pack purchase is a ``deposit`` credit
for the pack's USD value, so the existing :mod:`pry.commerce.billing_service`
drawdown/audit path is reused unchanged. No second payment system: the x402
verify/settle machinery in :mod:`pry.payments.x402` is the only rail.

Fail-closed wallet rule
-----------------------
A pack purchase NEVER emits a placeholder payTo. If the receiving wallet for
the resolved network is unconfigured (:func:`pry.payments.x402.wallet_configured`
returns False), :func:`create_pack_invoice` raises :class:`PackWalletUnconfigured`
instead of minting a manifest with a fake payTo.

NOTES / REVIEW
--------------
- The self-facilitator is overridable in tests by monkeypatching
  ``packs._get_self_facilitator`` to return a fake exposing
  ``async verify(payment) -> VerifyResult`` (verify/settlement resolve it
  through this module at call time).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import Any

from pry.commerce.billing.accounts import signup_crypto
from pry.commerce.billing.catalog import (
    PACKS,
    SCRAPE_CREDIT_USD,
    STARTER_CREDITS_USD,
    Pack,
    PackNotFound,
    PackWalletUnconfigured,
    Underpayment,
    get_pack,
    list_packs,
)
from pry.commerce.billing.clock import now, utc_iso
from pry.commerce.billing.confirm import confirm_pack_purchase, confirm_pack_purchase_async
from pry.commerce.billing.store import (
    ENV_PACK_STORE_FILE,
    register_invoice,
    reset_pack_state,
    save_state_locked,
    set_pack_store_path,
)
from pry.commerce.billing.verify import verify_pack_payment, verify_pack_payment_async
from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    X402_NETWORK_WALLETS,
    X402_WALLET,
    resolve_pay_to,
    wallet_configured,
)
from pry.payments.x402.scheme import (
    X402Scheme,
    asset_to_atomic,
    build_payment_required,
    normalize_network_id,
)

__all__ = [
    "ENV_PACK_STORE_FILE",
    "PACKS",
    "SCRAPE_CREDIT_USD",
    "STARTER_CREDITS_USD",
    "Pack",
    "PackNotFound",
    "PackWalletUnconfigured",
    "Underpayment",
    "confirm_pack_purchase",
    "confirm_pack_purchase_async",
    "create_pack_invoice",
    "get_pack",
    "list_packs",
    "reset_pack_state",
    "set_pack_store_path",
    "signup_crypto",
    "submit_pack_payment",
    "verify_pack_payment",
    "verify_pack_payment_async",
]

#: Invoice validity in seconds (default 24h).
ENV_PACK_INVOICE_TTL: str = "PRY_PACK_INVOICE_TTL"
_DEFAULT_INVOICE_TTL: int = 86_400


def _public_base_url() -> str:
    """Canonical public base URL for payment-manifest resource fields.

    Env override PRY_PUBLIC_BASE_URL; defaults to the production API.
    """
    return os.getenv("PRY_PUBLIC_BASE_URL", "https://api.pryscraper.com").rstrip("/")


def _invoice_ttl_seconds() -> int:
    """Invoice validity window (env override, default 24h)."""
    try:
        value = int(os.environ.get(ENV_PACK_INVOICE_TTL, str(_DEFAULT_INVOICE_TTL)))
        return value if value > 0 else _DEFAULT_INVOICE_TTL
    except ValueError:
        return _DEFAULT_INVOICE_TTL


def _resolve_pay_to(network: str) -> str:
    """Resolve the receiving wallet for *network*.

    Returns the wallet address, or raises :class:`PackWalletUnconfigured`
    when the resolved wallet is a placeholder / unconfigured. This is the
    fail-closed gate: a pack purchase NEVER returns a fake payTo.
    """
    pay_to = resolve_pay_to(
        network, wallets=X402_NETWORK_WALLETS, evm_wallet=X402_WALLET
    )  # family-aware; "" (fails closed) when unconfigured
    if not wallet_configured(pay_to):
        raise PackWalletUnconfigured(
            f"no real receiving wallet configured for network '{network}' — "
            "refusing to emit a placeholder payTo"
        )
    return pay_to


def create_pack_invoice(
    pack_id: str,
    *,
    user_id: str = "",
    api_key: str = "",
    network: str = "",
    asset: str = "",
) -> dict[str, Any]:
    """Create an x402 PaymentRequired manifest for buying *pack_id*.

    Returns a dict with ``invoice_id``, ``pack_id``, ``amount_usd``,
    ``amount_atomic``, ``credits``, ``chain``, ``pay_to``, ``expires_at``,
    ``payment_method`` and the spec ``payment_required`` x402 body. Raises:

    - :class:`PackNotFound` — unknown pack
    - :class:`PackWalletUnconfigured` — no real receiving wallet configured
      for the resolved network (FAIL CLOSED — never a placeholder payTo)

    Ties the manifest to ``user_id``/``api_key`` so a verified payment credits
    the right account (or mints a key on first purchase).
    """
    pack = get_pack(pack_id)
    asset = (asset or X402_DEFAULT_ASSET).upper()
    network = normalize_network_id(network or X402_DEFAULT_NETWORK)
    chain = network
    amount_atomic = asset_to_atomic(pack.price_usd, asset, network)
    pay_to = _resolve_pay_to(network)  # fails closed → raises PackWalletUnconfigured

    invoice_id = f"pack_{uuid.uuid4().hex[:12]}"
    resource = f"{_public_base_url()}/api/billing/purchase/{invoice_id}"
    description = f"{pack.description} — Bulk scrape credits ({pack.credits:,})"

    accepts: list[dict[str, Any]] = [
        {
            "scheme": X402Scheme.EXACT.value,
            "network": chain,
            "maxAmountRequired": str(amount_atomic),
            "resource": resource,
            "description": description,
            "mimeType": "application/json",
            "payToAddress": pay_to,
            "asset": asset,
            "extra": {
                "name": asset,
                "version": "2",
                "operation": "billing_pack_purchase",
                "pack_id": pack.id,
                "invoice_id": invoice_id,
                "priceUsd": pack.price_usd,
                "credits": pack.credits,
            },
        }
    ]
    body = build_payment_required(
        "billing_pack_purchase",
        resource=resource,
        accepts=accepts,
        description=description,
    )
    expires_at = utc_iso(now() + timedelta(seconds=_invoice_ttl_seconds()))

    record: dict[str, Any] = {
        "invoice_id": invoice_id,
        "pack_id": pack.id,
        "user_id": user_id,
        "api_key": api_key,
        "payment_method": "x402",
        "amount_usd": pack.price_usd,
        "amount_atomic": amount_atomic,
        "amount_asset": str(amount_atomic),
        "chain": chain,
        "pay_to": pay_to,
        "asset": asset,
        "expires_at": expires_at,
        "status": "pending",
        "payment": {
            "payment_id": invoice_id,
            "network": chain,
            "asset": asset,
            "amount_usd": pack.price_usd,
            "tx_hash": None,
            "authorization": None,
        },
        "x402_body": body,
    }
    register_invoice(record)
    return {
        "invoice_id": invoice_id,
        "pack_id": pack.id,
        "amount_usd": pack.price_usd,
        "amount_atomic": amount_atomic,
        "credits": pack.credits,
        "chain": chain,
        "pay_to": pay_to,
        "asset": asset,
        "expires_at": expires_at,
        "payment_method": "x402",
        "payment_required": body,
    }


def submit_pack_payment(
    invoice_id: str,
    tx_hash: str,
    network: str = "",
    asset: str = "",
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach the payer's on-chain tx (and optional EIP-3009 authorization).

    Companion step between checkout (``create_pack_invoice``) and verification
    (``verify_pack_payment``). Raises ``ValueError`` for unknown invoices or
    empty tx hashes. Returns the updated invoice record.
    """
    from pry.commerce.billing.store import ensure_loaded, invoices, lock

    if not tx_hash or not tx_hash.strip():
        raise ValueError("tx_hash must be a non-empty transaction hash")
    ensure_loaded()
    with lock:
        invoice = invoices.get(invoice_id)
        if invoice is None:
            raise ValueError(f"unknown pack invoice {invoice_id!r}")
        if invoice.get("payment_method") != "x402":
            raise ValueError("submit_pack_payment is only valid for x402 invoices")
        payment = invoice["payment"]
        payment["tx_hash"] = tx_hash.strip()
        if network:
            payment["network"] = normalize_network_id(network)
        if asset:
            payment["asset"] = asset.upper()
        if authorization is not None:
            payment["authorization"] = authorization
        invoice["status"] = "submitted"
        save_state_locked()
    return dict(invoice)


def _get_self_facilitator() -> Any:
    """Build the self-facilitator used for pack verification.

    Overridable in tests: monkeypatch ``billing.packs._get_self_facilitator``
    to return a fake exposing ``async verify(payment) -> VerifyResult``.
    """
    from pry.payments.x402.self_facilitator import SelfFacilitator

    return SelfFacilitator(pay_to=X402_WALLET)
