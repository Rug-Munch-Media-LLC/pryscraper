"""Pry — bulk scrape-credit packs (crypto checkout via x402 self-facilitation).

Lets a user buy a BULK of scrape credits with USDC over Pry's own x402
self-facilitation rail (EIP-3009 on EVM / SPL on Solana) — no email, no
third-party processor, no KYC. The pack catalog carries server-authoritative
prices in atomic units; a verified payment is settled against the existing
prepaid USD ledger (:mod:`pry.commerce.billing_service`) and an API key is
minted on first purchase (crypto signup).

Pricing model
-------------
A scrape credit is worth ``SCRAPE_CREDIT_USD`` (USD). Packs are sold at a
USD price and credit the balance with ``credits`` scrape credits:
``credits * SCRAPE_CREDIT_USD == price_usd`` (server-authoritative). The LEDGER
remains USD-denominated — a pack purchase is a ``deposit`` credit for the pack's
USD value, so the existing :mod:`pry.commerce.billing_service` drawdown/audit
path is reused unchanged. No second payment system: the x402 verify/settle
machinery in :mod:`pry.payments.x402` is the only rail.

Fail-closed wallet rule
-----------------------
A pack purchase NEVER emits a placeholder payTo. If the receiving wallet for
the resolved network is unconfigured (:func:`pry.payments.x402.wallet_configured`
returns False), :func:`create_pack_invoice` raises :class:`PackWalletUnconfigured`
instead of minting a manifest with a fake payTo.

NOTES / REVIEW
--------------
- ``confirm_pack_purchase`` is the SYNC public API (``asyncio.run`` bridge,
  mirroring ``billing.subscription``) — good for CLI / tests / sync routes.
  ``confirm_pack_purchase_async`` is the ASYNC variant for FastAPI routes and
  other running event loops. Both share :func:`_settle_pack_purchase`.
- Invoices are tracked in-memory (plus optional JSON persistence via
  :func:`set_pack_store_path`) so confirm is idempotent and survives restarts
  best-effort — the same contract as ``billing.subscription``.
- The self-facilitator is overridable in tests by monkeypatching
  ``packs._get_self_facilitator`` to return a fake exposing
  ``async verify(payment) -> VerifyResult``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pry.commerce import billing_service
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
from pry.payments.x402.self_facilitator import SelfFacilitator

logger = logging.getLogger(__name__)

#: Scrape-credit value in USD (matches the ``scrape`` x402 operation price,
#: so one pack credit == one on-demand scrape).
SCRAPE_CREDIT_USD: float = 0.001

#: Env var for the optional JSON persistence file (pack invoices).
ENV_PACK_STORE_FILE: str = "PRY_PACKS_STORE_FILE"
#: Invoice validity in seconds (default 24h).
ENV_PACK_INVOICE_TTL: str = "PRY_PACK_INVOICE_TTL"
_DEFAULT_INVOICE_TTL: int = 86_400

#: Persistence file format version.
_PERSIST_VERSION: int = 1

#: In-memory pack invoice registry (keyed by invoice_id).
_INVOICES: dict[str, dict[str, Any]] = {}
#: Explicit store path set via :func:`set_pack_store_path`.
_configured_store_path: Path | None = None
_lock = threading.RLock()


@dataclass(frozen=True, slots=True)
class Pack:
    """A scrape-credit pack with server-authoritative pricing.

    Attributes:
        id: Canonical pack id (``starter``, ``growth``, ``bulk``).
        price_usd: USD list price of the pack (the x402 amount quoted).
        credits: Number of scrape credits granted (``price_usd / SCRAPE_CREDIT_USD``).
        description: Human-readable summary.
    """

    id: str
    price_usd: float
    credits: int
    description: str

    @property
    def credits_usd(self) -> float:
        """USD value of the credits granted (== ``price_usd``)."""
        return round(self.credits * SCRAPE_CREDIT_USD, 6)

    @property
    def amount_atomic(self) -> int:
        """Server-authoritative x402 amount in atomic units for the default asset."""
        return asset_to_atomic(self.price_usd, X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK)


class PackWalletUnconfigured(Exception):
    """Raised when no real receiving wallet is configured for the pack network.

    Fail-closed: the caller must NOT emit a placeholder payTo. The operator
    must configure a real wallet (env or secret) before accepting pack
    purchases on the resolved network.
    """


class PackNotFound(Exception):
    """Raised for an unknown pack id."""


class Underpayment(Exception):
    """Raised when a pack payment is reported but does not verify / under-pays.

    Carries a ``reason`` so callers can surface an actionable message.
    """

    def __init__(self, message: str, *, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


#: Canonical pack catalog. Keep ids lowercase and stable — they are the
#: machine-readable key an agent passes to ``POST /v1/billing/purchase``.
PACKS: dict[str, Pack] = {
    "starter": Pack(
        id="starter",
        price_usd=5.0,
        credits=5000,
        description="5,000 scrape credits (~500 full pages)",
    ),
    "growth": Pack(
        id="growth",
        price_usd=20.0,
        credits=20000,
        description="20,000 scrape credits (~2,000 full pages)",
    ),
    "bulk": Pack(
        id="bulk",
        price_usd=100.0,
        credits=100000,
        description="100,000 scrape credits (~10,000 full pages)",
    ),
}

#: Starter credits granted on crypto signup (no email).
STARTER_CREDITS_USD: float = 1.0


# ── Time helpers (monkeypatchable for tests) ────────────────────────────────
def _now() -> datetime:
    """Current UTC timestamp (single hook so tests can freeze time)."""
    return datetime.now(UTC)


def _utc_iso(dt: datetime) -> str:
    """ISO-8601 with explicit UTC offset (round-trips via fromisoformat)."""
    return dt.isoformat()


def _parse_iso(value: str) -> datetime:
    """Parse a stored ISO timestamp back into an aware datetime."""
    return datetime.fromisoformat(value)


def get_pack(pack_id: str) -> Pack:
    """Resolve *pack_id* to a :class:`Pack`.

    Case-insensitive, whitespace-tolerant. Raises :class:`PackNotFound` for
    unknown ids (the route turns this into a 404/400 — never silently default).
    """
    if not pack_id:
        raise PackNotFound("pack id is required")
    pack = PACKS.get(pack_id.strip().lower())
    if pack is None:
        raise PackNotFound(f"unknown pack '{pack_id}'")
    return pack


def list_packs() -> list[dict[str, Any]]:
    """Return the pack catalog (machine-readable, prices in atomic units)."""
    out: list[dict[str, Any]] = []
    for pack in PACKS.values():
        out.append(
            {
                "id": pack.id,
                "price_usd": pack.price_usd,
                "credits": pack.credits,
                "credits_usd": pack.credits_usd,
                "amount_atomic": pack.amount_atomic,
                "description": pack.description,
                "asset": X402_DEFAULT_ASSET,
                "network": X402_DEFAULT_NETWORK,
                "credit_usd": SCRAPE_CREDIT_USD,
            }
        )
    return out


# ── Invoice creation ────────────────────────────────────────────────────────
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
    resource = f"https://pry.dev/api/billing/purchase/{invoice_id}"
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
    expires_at = _utc_iso(_now() + timedelta(seconds=_invoice_ttl_seconds()))

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
    _register_invoice(record)
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


def _invoice_ttl_seconds() -> int:
    """Invoice validity window (env override, default 24h)."""
    try:
        value = int(os.environ.get(ENV_PACK_INVOICE_TTL, str(_DEFAULT_INVOICE_TTL)))
        return value if value > 0 else _DEFAULT_INVOICE_TTL
    except ValueError:
        return _DEFAULT_INVOICE_TTL


# ── Payment submission + verification ───────────────────────────────────────
def submit_pack_payment(
    invoice_id: str,
    tx_hash: str,
    network: str = "",
    asset: str = "",
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach the payer's on-chain tx (and optional EIP-3009 authorization).

    Companion step between checkout (``create_pack_invoice``) and verification
    (``confirm_pack_purchase``). Raises ``ValueError`` for unknown invoices or
    empty tx hashes. Returns the updated invoice record.
    """
    if not tx_hash or not tx_hash.strip():
        raise ValueError("tx_hash must be a non-empty transaction hash")
    with _lock:
        invoice = _INVOICES.get(invoice_id)
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
        _save_state_locked()
    return dict(invoice)


def verify_pack_payment(invoice_id: str) -> dict[str, Any]:
    """Check the on-chain payment for a pack invoice via the self-facilitator.

    Returns ``{paid: bool, tx_hash, confirmed_at, reason, status, signer?}``.
    An invoice with no reported tx is unpaid. Expired invoices fail closed
    unless the payment verifies.
    """
    _ensure_loaded()
    with _lock:
        invoice = _INVOICES.get(invoice_id)
    if invoice is None:
        return {"paid": False, "tx_hash": None, "confirmed_at": None, "reason": "unknown invoice"}
    now = _now()
    try:
        expires_at = _parse_iso(str(invoice["expires_at"]))
    except ValueError:
        expires_at = now  # malformed persistence → fail closed
    expired = now >= expires_at
    return _verify_x402(invoice, expired=expired)


async def verify_pack_payment_async(invoice_id: str) -> dict[str, Any]:
    """Async :func:`verify_pack_payment` (safe inside a running event loop)."""
    _ensure_loaded()
    with _lock:
        invoice = _INVOICES.get(invoice_id)
    if invoice is None:
        return {"paid": False, "tx_hash": None, "confirmed_at": None, "reason": "unknown invoice"}
    now = _now()
    try:
        expires_at = _parse_iso(str(invoice["expires_at"]))
    except ValueError:
        expires_at = now
    expired = now >= expires_at
    return await _verify_x402_async(invoice, expired=expired)


def _verify_x402(invoice: dict[str, Any], *, expired: bool) -> dict[str, Any]:
    """Sync verify: bridge the async self-facilitator via ``asyncio.run``."""
    return asyncio.run(_verify_x402_async(invoice, expired=expired))


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

    verification = await _get_self_facilitator().verify(
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
    """Build the self-facilitator used for pack verification.

    Overridable in tests: monkeypatch ``billing.packs._get_self_facilitator``
    to return a fake exposing ``async verify(payment) -> VerifyResult``.
    """
    return SelfFacilitator(pay_to=X402_WALLET)


# ── Settlement: credit the ledger + crypto signup ───────────────────────────
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

    1. Attach ``tx_hash`` via :func:`submit_pack_payment`.
    2. :func:`verify_pack_payment` via the self-facilitator.
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
    _ensure_loaded()
    with _lock:
        invoice = _INVOICES.get(invoice_id)
        if invoice is None:
            raise ValueError(f"unknown pack invoice {invoice_id!r}")
        _bind_account(invoice, user_id=user_id, api_key=api_key)
        account_user_id = invoice.get("user_id") or ""
        account_api_key = invoice.get("api_key") or ""
        amount_usd = invoice["amount_usd"]
        pack_id = invoice["pack_id"]
    _save_state_locked()

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
    :func:`_settle_pack_purchase`. Identical contract to the sync variant.
    """
    if not tx_hash or not tx_hash.strip():
        raise ValueError("tx_hash must be a non-empty transaction hash")
    _ensure_loaded()
    with _lock:
        invoice = _INVOICES.get(invoice_id)
        if invoice is None:
            raise ValueError(f"unknown pack invoice {invoice_id!r}")
        _bind_account(invoice, user_id=user_id, api_key=api_key)
        account_user_id = invoice.get("user_id") or ""
        account_api_key = invoice.get("api_key") or ""
        amount_usd = invoice["amount_usd"]
        pack_id = invoice["pack_id"]
    _save_state_locked()

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
    with _lock:
        invoice = _INVOICES.get(invoice_id)
    if invoice is None:
        return
    payment = invoice.get("payment", {})
    if payment.get("tx_hash") != tx_hash.strip() or network or asset:
        submit_pack_payment(invoice_id, tx_hash, network=network, asset=asset)


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

    Settlement gate: verify alone only ecrecovers the EIP-3009 authorization —
    funds do not move until the self-facilitator broadcasts the settlement
    (``SelfFacilitator.settle``). Credits are granted ONLY when settlement
    succeeds; a failed broadcast returns a payment-failed result and the
    ledger is never touched.
    """
    pack = get_pack(pack_id)
    reference = f"pack:{invoice_id}:{tx_hash}"

    # ── On-chain settlement (EIP-3009 transferFrom via the authorization) ──
    with _lock:
        payment = dict(_INVOICES[invoice_id].get("payment") or {})
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

    with _lock:
        stored_ref = _INVOICES[invoice_id].get("credited_reference")
        already_credited = stored_ref == reference

    if already_credited:
        balance = billing_service.get_balance(user_id)
        credited = {"balance_usd": balance["balance_usd"]}
    else:
        credited = billing_service.credit(
            user_id, pack.price_usd, reason="deposit", reference=reference
        )
        with _lock:
            _INVOICES[invoice_id]["credited_reference"] = reference
            _save_state_locked()

    resolved_key = api_key
    if mint_key and not resolved_key:
        issued = _mint_key(user_id, pack.id)
        resolved_key = issued["plaintext"]
        with _lock:
            _INVOICES[invoice_id]["api_key"] = resolved_key
            _save_state_locked()

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
    return await _get_self_facilitator().settle(payment)


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


def _pack_amount_atomic(pack_id: str) -> int:
    try:
        return get_pack(pack_id).amount_atomic
    except PackNotFound:
        return 0


def _bind_account(invoice: dict[str, Any], *, user_id: str = "", api_key: str = "") -> None:
    """Resolve (and persist on the invoice) the account receiving the credit.

    Precedence: explicit ``user_id``, then ``api_key``'s owner (via
    :func:`pry.core.api_keys_service.authenticate`), then the binding stored
    on the invoice (first submission wins), then a fresh primary account.
    Mutable — writes ``user_id``/``api_key`` onto ``invoice``.
    """
    from pry.core.api_keys_service import PRIMARY_USER_ID, authenticate

    if user_id:
        invoice["user_id"] = user_id
        if api_key:
            invoice["api_key"] = api_key
        return
    if api_key:
        record = authenticate(api_key)
        owner = record["user_id"] if record else PRIMARY_USER_ID
        invoice["user_id"] = owner
        invoice["api_key"] = api_key
        return
    if not invoice.get("user_id"):
        invoice["user_id"] = PRIMARY_USER_ID


def _mint_key(user_id: str, pack_id: str) -> dict[str, Any]:
    """Mint an API key for *user_id* on a successful pack purchase (no email).

    The plaintext is returned once and stored hashed at rest.
    """
    from pry.core.api_keys_service import issue_key

    return issue_key(
        user_id=user_id,
        name=f"pack-{pack_id}-signup" if pack_id else "signup",
        tier="FREE",
        scopes=["scrape", "crawl", "x402", "billing"],
    )


# ── Crypto signup (no email) ────────────────────────────────────────────────
def signup_crypto(user_id: str = "", api_key: str = "") -> dict[str, Any]:
    """Issue a key + starter credits with no email.

    When ``api_key`` is supplied and still active it is returned as-is (no
    duplicate key minted); otherwise a fresh key is minted for ``user_id``
    (or the implicit primary account). Grants ``STARTER_CREDITS_USD`` USD of
    prepaid balance (reason=``grant``, reference=``signup``) exactly once.
    Returns ``{api_key, user_id, created, starter_credits_usd}``.
    """
    if api_key:
        from pry.core.api_keys_service import authenticate

        record = authenticate(api_key)
        if record:
            return {"api_key": api_key, "user_id": record["user_id"], "created": False}
    from pry.core.api_keys_service import PRIMARY_USER_ID

    target_user_id = user_id or PRIMARY_USER_ID
    issued = _mint_key(target_user_id, "signup")
    if not _has_starter_credit(target_user_id):
        billing_service.credit(
            target_user_id, STARTER_CREDITS_USD, reason="grant", reference="signup"
        )
    return {
        "api_key": issued["plaintext"],
        "user_id": target_user_id,
        "created": True,
        "starter_credits_usd": STARTER_CREDITS_USD,
    }


def _has_starter_credit(user_id: str) -> bool:
    """True if this user already consumed the ``signup`` grant (idempotency)."""
    try:
        entries = billing_service.ledger(user_id, limit=100)
    except Exception:  # noqa: BLE001 - never block signup on a ledger error
        return False
    return any(e.get("reference") == "signup" for e in entries)


# ── Persistence ─────────────────────────────────────────────────────────────
def set_pack_store_path(path: str | Path | None) -> None:
    """Enable/disable JSON persistence of pack invoices.

    Pass a path to persist there (atomic writes); ``None`` disables and falls
    back to the ``PRY_PACKS_STORE_FILE`` env var. Best-effort: I/O errors are
    logged, never raised.
    """
    global _configured_store_path
    _configured_store_path = Path(path) if path else None


def reset_pack_state() -> None:
    """Clear the in-memory pack invoice registry (test/ops helper)."""
    with _lock:
        _INVOICES.clear()


def _store_path() -> Path | None:
    """Resolve the persistence file path, or None when persistence is off."""
    if _configured_store_path is not None:
        return _configured_store_path
    env_path = os.environ.get(ENV_PACK_STORE_FILE)
    return Path(env_path) if env_path else None


def _ensure_loaded() -> None:
    """Load persisted state from disk when the registry is empty."""
    with _lock:
        _ensure_loaded_locked()


def _ensure_loaded_locked() -> None:
    """Load persisted state from disk. Callers must hold ``_lock``."""
    path = _store_path()
    if path is None or _INVOICES or not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable pack store %s: %s", path, exc)
        return
    if not isinstance(payload, dict) or payload.get("version") != _PERSIST_VERSION:
        logger.warning("Ignoring incompatible pack store %s", path)
        return
    invoices = payload.get("invoices")
    if isinstance(invoices, dict):
        _INVOICES.update({str(k): v for k, v in invoices.items() if isinstance(v, dict)})


def _register_invoice(record: dict[str, Any]) -> None:
    """Store a new pack invoice and persist. Callers must NOT hold the lock."""
    with _lock:
        _INVOICES[record["invoice_id"]] = record
        _save_state_locked()


def _save_state_locked() -> None:
    """Best-effort atomic persist of pack invoices."""
    path = _store_path()
    if path is None:
        return
    payload: dict[str, Any] = {
        "version": _PERSIST_VERSION,
        "invoices": _INVOICES,
    }
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        logger.error("Failed to persist pack store %s: %s", path, exc)
