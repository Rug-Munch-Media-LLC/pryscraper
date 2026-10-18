"""Pry — subscription invoice creation (x402 default + BTCPay fallback).

Invoice creation for the monthly tiers defined in :mod:`billing.tiers`:

- **x402** (default): builds a spec-compliant x402 ``PaymentRequired`` via
  :func:`x402.scheme.build_payment_required` quoting the tier's monthly
  price, using the self-facilitator wallet as ``payToAddress``.
- **btcpay** (fallback): when ``PRY_BTCPAY_URL`` + ``PRY_BTCPAY_API_KEY`` +
  ``PRY_BTCPAY_STORE`` are configured, invoices are created via BTCPay
  Server's REST API (``POST /api/v1/stores/{store}/invoices``).

Also exposes :func:`submit_subscription_payment` — the companion step
between checkout and verification where the payer reports the on-chain tx
hash (plus the EIP-3009 authorization for the self-facilitator flow).

Patchable dependencies (``_now``, ``build_payment_required``, ``X402_WALLET``,
``X402_NETWORK_WALLETS``) are resolved through the
:mod:`pry.commerce.billing.subscription` facade at call time so tests can
monkeypatch the facade.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import contextlib
import logging
import os
import uuid
from datetime import timedelta
from typing import Any

import httpx

from pry.commerce.billing import subscription as _facade
from pry.commerce.billing.subscription_state import (
    _INVOICES,
    _lock,
    _register_invoice,
    _save_state_locked,
)
from pry.commerce.billing.subscription_time import _parse_iso, _utc_iso
from pry.commerce.billing.tiers import TIERS, get_tier
from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    resolve_pay_to,
)
from pry.payments.x402.scheme import X402Scheme, asset_to_atomic, normalize_network_id

logger = logging.getLogger(__name__)

#: Env vars for the BTCPay Server fallback backend.
ENV_BTCPAY_URL: str = "PRY_BTCPAY_URL"
ENV_BTCPAY_API_KEY: str = "PRY_BTCPAY_API_KEY"
ENV_BTCPAY_STORE: str = "PRY_BTCPAY_STORE"
#: Invoice validity in seconds (default 24h).
ENV_INVOICE_TTL: str = "PRY_SUBSCRIPTION_INVOICE_TTL"
_DEFAULT_INVOICE_TTL: int = 86_400


def _public_base_url() -> str:
    """Canonical public base URL for payment-manifest resource fields.

    Env override PRY_PUBLIC_BASE_URL; defaults to the production API. The
    resource URL is what agents see in the 402 manifest — it must point at
    a domain we actually serve (pry.dev was a placeholder we do not own).
    """
    return os.getenv("PRY_PUBLIC_BASE_URL", "https://api.pryscraper.com").rstrip("/")


# ── Backend selection ───────────────────────────────────────────────────────
def _btcpay_env() -> tuple[str, str, str] | None:
    """Return ``(url, api_key, store)`` when BTCPay is configured, else None."""
    url = os.environ.get(ENV_BTCPAY_URL, "").strip().rstrip("/")
    api_key = os.environ.get(ENV_BTCPAY_API_KEY, "").strip()
    store = os.environ.get(ENV_BTCPAY_STORE, "").strip()
    if url and api_key and store:
        return url, api_key, store
    if (url or api_key) and not store:
        logger.warning(
            "%s set without %s — BTCPay backend disabled (store id required); falling back to x402",
            ENV_BTCPAY_URL,
            ENV_BTCPAY_STORE,
        )
    return None


# ── Invoice creation ────────────────────────────────────────────────────────
def create_subscription_invoice(
    tier: str,
    api_key: str,
    months: int = 1,
    *,
    amount_override_usd: float | None = None,
) -> dict[str, Any]:
    """Create a crypto payment invoice for *months* of *tier*.

    Returns a dict with ``invoice_id``, ``tier``, ``amount_usd``,
    ``amount_asset``, ``chain``, ``payment_address``, ``expires_at``,
    ``payment_method`` (plus ``asset`` so the amount can be interpreted).
    Two backends:

    - **x402** (default): builds an x402 ``PaymentRequired`` acceptance for
      the monthly amount via :func:`x402.scheme.build_payment_required`, using
      the self-facilitator wallet as ``payToAddress``.
    - **btcpay**: when ``PRY_BTCPAY_URL`` + ``PRY_BTCPAY_API_KEY`` +
      ``PRY_BTCPAY_STORE`` are set, creates a BTCPay Server invoice via
      ``POST {url}/api/v1/stores/{store}/invoices``.

    ``amount_override_usd`` quotes a caller-computed amount instead of the
    list price (used for a prorated tier-change difference); it must be > 0.
    The invoice still carries the target tier and month count so payment
    confirmation activates exactly what was paid for.

    Raises ``ValueError`` for unknown tiers or tiers without a fixed monthly
    price (``free`` / ``enterprise``).
    """
    resolved = get_tier(tier)
    if resolved.price_usd_monthly is None:
        raise ValueError(
            f"tier {resolved.name!r} has no fixed monthly price — "
            "cannot create a subscription invoice"
        )
    months = _validate_months(months)
    if amount_override_usd is None:
        amount_usd = round(resolved.price_usd_monthly * months, 2)
    else:
        amount_usd = round(float(amount_override_usd), 2)
        if amount_usd <= 0:
            raise ValueError("amount_override_usd must be > 0")

    btcpay = _btcpay_env()
    if btcpay is not None:
        return _create_btcpay_invoice(btcpay, resolved.name, api_key, months, amount_usd)
    return _create_x402_invoice(resolved.name, api_key, months, amount_usd)


def _validate_months(months: int) -> int:
    """Coerce *months* to a positive int, raising ValueError otherwise."""
    if isinstance(months, bool) or not isinstance(months, int):
        raise ValueError("months must be a positive integer")
    if months < 1:
        raise ValueError("months must be >= 1")
    return months


def _invoice_ttl_seconds() -> int:
    """Invoice validity window (env override, default 24h)."""
    try:
        value = int(os.environ.get(ENV_INVOICE_TTL, str(_DEFAULT_INVOICE_TTL)))
        return value if value > 0 else _DEFAULT_INVOICE_TTL
    except ValueError:
        return _DEFAULT_INVOICE_TTL


def _create_x402_invoice(
    tier_name: str, api_key: str, months: int, amount_usd: float
) -> dict[str, Any]:
    """Build an x402 PaymentRequired invoice for the monthly amount."""
    asset = X402_DEFAULT_ASSET
    network = X402_DEFAULT_NETWORK
    chain = normalize_network_id(network)
    amount_atomic = asset_to_atomic(amount_usd, asset, network)
    payment_address = resolve_pay_to(
        chain, wallets=_facade.X402_NETWORK_WALLETS, evm_wallet=_facade.X402_WALLET
    )  # family-aware; "" when unconfigured
    invoice_id = f"inv_{uuid.uuid4().hex[:12]}"
    resource = f"{_public_base_url()}/api/billing/subscription/{invoice_id}"
    description = f"{TIERS[tier_name].name.title()} subscription ({months} month(s))"

    accepts: list[dict[str, Any]] = [
        {
            "scheme": X402Scheme.EXACT.value,
            "network": chain,
            "maxAmountRequired": str(amount_atomic),
            "resource": resource,
            "description": description,
            "mimeType": "application/json",
            "payToAddress": payment_address,
            "asset": asset,
            "extra": {
                "name": asset,
                "version": "2",
                "operation": "subscription",
                "tier": tier_name,
                "months": months,
                "invoice_id": invoice_id,
                "priceUsd": amount_usd,
            },
        }
    ]
    body = _facade.build_payment_required(
        "subscription",
        resource=resource,
        accepts=accepts,
        description=description,
    )
    expires_at = _utc_iso(_facade._now() + timedelta(seconds=_invoice_ttl_seconds()))

    record: dict[str, Any] = {
        "invoice_id": invoice_id,
        "tier": tier_name,
        "api_key": api_key,
        "months": months,
        "payment_method": "x402",
        "amount_usd": amount_usd,
        "amount_asset": str(amount_atomic),
        "chain": chain,
        "payment_address": payment_address,
        "expires_at": expires_at,
        "status": "pending",
        "payment": {
            "payment_id": invoice_id,
            "network": chain,
            "asset": asset,
            "amount_usd": amount_usd,
            "tx_hash": None,
            "authorization": None,
        },
        "x402_body": body,
    }
    _register_invoice(record)
    return {
        "invoice_id": invoice_id,
        "tier": tier_name,
        "amount_usd": amount_usd,
        "amount_asset": str(amount_atomic),
        "chain": chain,
        "payment_address": payment_address,
        "expires_at": expires_at,
        "payment_method": "x402",
        "asset": asset,
    }


def _create_btcpay_invoice(
    btcpay: tuple[str, str, str],
    tier_name: str,
    api_key: str,
    months: int,
    amount_usd: float,
) -> dict[str, Any]:
    """Create an invoice via the BTCPay Server REST API."""
    url, token, store = btcpay
    order_id = f"sub_{uuid.uuid4().hex[:12]}"
    payload: dict[str, Any] = {
        "amount": f"{amount_usd:.2f}",
        "currency": "USD",
        "metadata": {
            "orderId": order_id,
            "tier": tier_name,
            "api_key": api_key,
            "months": months,
        },
    }
    response = httpx.post(
        f"{url}/api/v1/stores/{store}/invoices",
        json=payload,
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
        timeout=float(os.environ.get("PRY_BTCPAY_TIMEOUT", "15")),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError("BTCPay invoice response missing 'id'")

    invoice_id = str(data["id"])
    expires_at = _utc_iso(_facade._now() + timedelta(seconds=_invoice_ttl_seconds()))
    if isinstance(data.get("expirationTime"), str) and data["expirationTime"]:
        with contextlib.suppress(ValueError):
            expires_at = _utc_iso(_parse_iso(data["expirationTime"]))

    payment_address = _extract_btcpay_address(data)
    amount_asset = str(data.get("amount", amount_usd))

    record: dict[str, Any] = {
        "invoice_id": invoice_id,
        "tier": tier_name,
        "api_key": api_key,
        "months": months,
        "payment_method": "btcpay",
        "amount_usd": amount_usd,
        "amount_asset": amount_asset,
        "chain": "bitcoin",
        "payment_address": payment_address,
        "expires_at": expires_at,
        "status": "pending",
        "btcpay": {
            "order_id": order_id,
            "store": store,
            "upstream_status": data.get("status", "New"),
        },
    }
    _register_invoice(record)
    return {
        "invoice_id": invoice_id,
        "tier": tier_name,
        "amount_usd": amount_usd,
        "amount_asset": amount_asset,
        "chain": "bitcoin",
        "payment_address": payment_address,
        "expires_at": expires_at,
        "payment_method": "btcpay",
        "asset": "BTC",
    }


def _extract_btcpay_address(data: dict[str, Any]) -> str:
    """Pull the first on-chain address from a BTCPay invoice response."""
    addresses = data.get("addresses")
    if isinstance(addresses, dict):
        for value in addresses.values():
            if isinstance(value, str) and value:
                return value
    crypto_info = data.get("cryptoInfo")
    if isinstance(crypto_info, list):
        for item in crypto_info:
            if isinstance(item, dict) and isinstance(item.get("address"), str) and item["address"]:
                return str(item["address"])
    return ""


def _extract_btcpay_tx_hash(data: dict[str, Any]) -> str:
    """Pull the first settlement transaction id from a BTCPay invoice."""
    payments = data.get("payments")
    if isinstance(payments, list):
        for item in payments:
            if isinstance(item, dict) and item.get("transactionId"):
                return str(item["transactionId"])
    return ""


def submit_subscription_payment(
    invoice_id: str,
    tx_hash: str,
    network: str = "",
    asset: str = "",
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach the client's on-chain tx (and optional EIP-3009 authorization)
    to an x402 invoice so :func:`verify_subscription_payment` can check it.

    This is the companion step between checkout and verification: the payer
    broadcasts the payment and reports the tx hash (plus the EIP-3009
    authorization when using the self-facilitator flow). Returns the updated
    invoice record. Raises ``ValueError`` for unknown invoices or empty hashes.
    """
    if not tx_hash or not tx_hash.strip():
        raise ValueError("tx_hash must be a non-empty transaction hash")
    with _lock:
        invoice = _INVOICES.get(invoice_id)
        if invoice is None:
            raise ValueError(f"unknown invoice {invoice_id!r}")
        if invoice.get("payment_method") != "x402":
            raise ValueError("submit_subscription_payment is only valid for x402 invoices")
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
