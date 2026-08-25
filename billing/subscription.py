"""Pry — crypto subscription billing (monthly Pro/Team/Enterprise tiers).

Provider-flexible subscription invoicing + activation for the monthly tiers
defined in :mod:`billing.tiers`. Payments are collected in crypto through one
of two backends — there is NO hard dependency on any single acceptor:

- **x402** (default): reuses the existing self-facilitator machinery. Invoice
  creation builds a spec-compliant x402 ``PaymentRequired`` via
  :func:`x402.scheme.build_payment_required` quoting the tier's monthly price;
  verification delegates to :class:`x402.self_facilitator.SelfFacilitator`
  (``verify``) so an EIP-3009 authorization can be checked locally without
  touching Coinbase/CDP or any external facilitator.
- **btcpay** (fallback): when ``PRY_BTCPAY_URL`` + ``PRY_BTCPAY_API_KEY`` +
  ``PRY_BTCPAY_STORE`` are configured, invoices are created and polled via
  BTCPay Server's REST API (``POST/GET /api/v1/stores/{store}/invoices``).

Activation is provider-agnostic: :func:`activate_subscription` records an
expiry in an in-memory registry with optional JSON persistence at a
configurable path (``PRY_SUBSCRIPTIONS_FILE`` or
:func:`set_subscription_store_path`). This module is intentionally decoupled
from the API middleware — the lead integrator wires these functions into the
payment/checkout routes.

NOTES / REVIEW flags
--------------------
- ``verify_subscription_payment`` is a SYNC function (per the module contract)
  that runs the async :class:`SelfFacilitator.verify` via ``asyncio.run``.
  Call it from sync contexts (CLI, plain routes, tests). Calling it from
  inside a running event loop will raise ``RuntimeError`` — use
  :func:`verify_subscription_payment_async` there instead.
- BTCPay conversion (USD → BTC) happens server-side; ``amount_asset`` for the
  btcpay backend is the invoice amount as quoted by BTCPay (falling back to
  the USD amount string) — the exact BTC amount is known only after
  checkout. [REVIEW]
- The btcpay backend requires ``PRY_BTCPAY_STORE`` in addition to URL + API
  key because the REST endpoint is store-scoped. When the store id is
  missing the backend degrades to x402 with a logged warning. [REVIEW]
- ``usage`` in :func:`subscription_status` is read from a fresh
  :class:`billing.enforcer.BillingEnforcer` (per-call construction); it is a
  best-effort snapshot, not the exact counter state of the middleware's
  long-lived enforcer instance.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import calendar
import contextlib
import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from billing.enforcer import BillingEnforcer
from billing.tiers import TIERS, get_tier
from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    X402_NETWORK_WALLETS,
    X402_WALLET,
)
from pry.payments.x402.scheme import (
    X402Scheme,
    asset_to_atomic,
    build_payment_required,
    normalize_network_id,
)
from pry.payments.x402.self_facilitator import SelfFacilitator

if TYPE_CHECKING:
    from pry.payments.x402.self_facilitator import VerifyResult

logger = logging.getLogger(__name__)

#: Env vars for the BTCPay Server fallback backend.
ENV_BTCPAY_URL: str = "PRY_BTCPAY_URL"
ENV_BTCPAY_API_KEY: str = "PRY_BTCPAY_API_KEY"
ENV_BTCPAY_STORE: str = "PRY_BTCPAY_STORE"
#: Env var for the optional JSON persistence file (subscriptions + invoices).
ENV_SUBSCRIPTIONS_FILE: str = "PRY_SUBSCRIPTIONS_FILE"
#: Invoice validity in seconds (default 24h).
ENV_INVOICE_TTL: str = "PRY_SUBSCRIPTION_INVOICE_TTL"
_DEFAULT_INVOICE_TTL: int = 86_400

#: Persistence file format version.
_PERSIST_VERSION: int = 1

#: In-memory invoice registry (keyed by invoice_id).
_INVOICES: dict[str, dict[str, Any]] = {}
#: In-memory subscription registry (keyed by api_key).
_SUBSCRIPTIONS: dict[str, dict[str, Any]] = {}
#: Explicit store path set via :func:`set_subscription_store_path`.
_configured_store_path: Path | None = None
_lock = threading.RLock()


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


def _add_months(dt: datetime, months: int) -> datetime:
    """Add whole calendar months to *dt*, clamping the day-of-month."""
    month_index = dt.year * 12 + (dt.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


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
def create_subscription_invoice(tier: str, api_key: str, months: int = 1) -> dict[str, Any]:
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
    amount_usd = round(resolved.price_usd_monthly * months, 2)

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
    payment_address = X402_NETWORK_WALLETS.get(chain) or X402_WALLET
    invoice_id = f"inv_{uuid.uuid4().hex[:12]}"
    resource = f"https://pry.dev/api/billing/subscription/{invoice_id}"
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
    body = build_payment_required(
        "subscription",
        resource=resource,
        accepts=accepts,
        description=description,
    )
    expires_at = _utc_iso(_now() + timedelta(seconds=_invoice_ttl_seconds()))

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
    expires_at = _utc_iso(_now() + timedelta(seconds=_invoice_ttl_seconds()))
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

    now = _now()
    try:
        expires_at = _parse_iso(str(invoice["expires_at"]))
    except ValueError:
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


async def _verify_x402_payment(payment: dict[str, Any]) -> VerifyResult:
    """Async core: delegate verification to the self-facilitator."""
    return await _get_self_facilitator().verify(payment)


def _verify_x402_payment_sync(payment: dict[str, Any]) -> VerifyResult:
    """Bridge the async self-facilitator into the sync public API."""
    return asyncio.run(_verify_x402_payment(payment))


def _get_self_facilitator() -> SelfFacilitator:
    """Build the self-facilitator used for x402 verification.

    Overridable in tests: monkeypatch ``billing.subscription._get_self_facilitator``
    to return a fake exposing ``async verify(payment) -> VerifyResult``.
    """
    return SelfFacilitator(pay_to=X402_WALLET)


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
        if isinstance(data, dict):
            invoice.setdefault("btcpay", {})["upstream_status"] = status
        _save_state_locked()
    return {
        "paid": settled,
        "tx_hash": tx_hash or None,
        "confirmed_at": _utc_iso(_now()) if settled else None,
        "reason": "" if settled else ("expired" if expired else f"btcpay status {status}"),
        "status": "paid" if settled else ("expired" if expired else status),
    }


# ── Activation + status ─────────────────────────────────────────────────────
def activate_subscription(api_key: str, tier: str, months: int) -> dict[str, Any]:
    """Activate (or renew) a subscription for *api_key*.

    Computes the expiry as ``now + months`` calendar months, extending from
    the CURRENT expiry when the subscription is still active and the tier is
    unchanged (renewal rollover); an expired or downgraded subscription
    restarts from now. Records the subscription in-memory and, when a store
    path is configured, persists it best-effort.

    Returns ``{tier, expires_at}``. Raises ``ValueError`` for unpriced tiers.
    """
    resolved = get_tier(tier)
    if resolved.price_usd_monthly is None:
        raise ValueError(f"tier {resolved.name!r} has no fixed monthly price — cannot activate")
    months = _validate_months(months)

    now = _now()
    with _lock:
        _ensure_loaded_locked()
        previous = _SUBSCRIPTIONS.get(api_key)
        base = now
        if previous is not None:
            try:
                previous_expiry = _parse_iso(str(previous["expires_at"]))
            except ValueError:
                previous_expiry = now
            if previous_expiry > now and str(previous.get("tier", "")) == resolved.name:
                base = previous_expiry
        expires_at = _add_months(base, months)
        record: dict[str, Any] = {
            "api_key": api_key,
            "tier": resolved.name,
            "activated_at": _utc_iso(now),
            "expires_at": _utc_iso(expires_at),
            "months_paid": months,
        }
        _SUBSCRIPTIONS[api_key] = record
        _save_state_locked()
    return {"tier": resolved.name, "expires_at": _utc_iso(expires_at)}


def subscription_status(api_key: str) -> dict[str, Any]:
    """Return the current subscription state for *api_key*.

    Returns ``{tier, active, expires_at, usage}``; unknown keys report the
    FREE tier with no expiry. ``usage`` is a best-effort snapshot from a
    fresh :class:`billing.enforcer.BillingEnforcer` (see module NOTES).
    """
    _ensure_loaded()
    with _lock:
        record = _SUBSCRIPTIONS.get(api_key)
    if record is None:
        return {
            "tier": "free",
            "active": False,
            "expires_at": None,
            "usage": _usage_for(api_key),
        }
    now = _now()
    try:
        expires_at = _parse_iso(str(record["expires_at"]))
    except ValueError:
        expires_at = now
    return {
        "tier": str(record.get("tier", "free")),
        "active": expires_at > now,
        "expires_at": _utc_iso(expires_at),
        "usage": _usage_for(api_key),
    }


def _usage_for(api_key: str) -> dict[str, Any]:
    """Best-effort usage snapshot for *api_key* (never raises)."""
    try:
        stats = BillingEnforcer().usage_stats(api_key)
        return {
            "month_requests": int(stats.get("month_requests", 0)),
            "quota_remaining": stats.get("quota_remaining"),
            "quota_exceeded": bool(stats.get("quota_exceeded", False)),
        }
    except (OSError, ValueError, TypeError):
        return {"month_requests": 0, "quota_remaining": None, "quota_exceeded": False}


# ── Persistence ─────────────────────────────────────────────────────────────
def set_subscription_store_path(path: str | Path | None) -> None:
    """Enable/disable JSON persistence of subscriptions + invoices.

    Pass a path to persist state there (atomic writes); pass ``None`` to
    disable persistence and fall back to the ``PRY_SUBSCRIPTIONS_FILE`` env
    var. Best-effort: I/O errors are logged, never raised.
    """
    global _configured_store_path
    _configured_store_path = Path(path) if path else None


def reset_subscription_state() -> None:
    """Clear the in-memory registries (test/ops helper; disk untouched)."""
    with _lock:
        _INVOICES.clear()
        _SUBSCRIPTIONS.clear()


def _store_path() -> Path | None:
    """Resolve the persistence file path, or None when persistence is off."""
    if _configured_store_path is not None:
        return _configured_store_path
    env_path = os.environ.get(ENV_SUBSCRIPTIONS_FILE)
    return Path(env_path) if env_path else None


def _ensure_loaded() -> None:
    """Load persisted state from disk when the registries are empty."""
    with _lock:
        _ensure_loaded_locked()


def _ensure_loaded_locked() -> None:
    """Load persisted state from disk. Callers must hold ``_lock``."""
    path = _store_path()
    if path is None or _SUBSCRIPTIONS or _INVOICES or not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable subscription store %s: %s", path, exc)
        return
    if not isinstance(payload, dict) or payload.get("version") != _PERSIST_VERSION:
        logger.warning("Ignoring incompatible subscription store %s", path)
        return
    invoices = payload.get("invoices")
    subscriptions = payload.get("subscriptions")
    if isinstance(invoices, dict):
        _INVOICES.update({str(k): v for k, v in invoices.items() if isinstance(v, dict)})
    if isinstance(subscriptions, dict):
        _SUBSCRIPTIONS.update({str(k): v for k, v in subscriptions.items() if isinstance(v, dict)})


def _register_invoice(record: dict[str, Any]) -> None:
    """Store a new invoice and persist. Callers must NOT hold the lock."""
    with _lock:
        _INVOICES[record["invoice_id"]] = record
        _save_state_locked()


def _save_state_locked() -> None:
    """Best-effort atomic persist of invoices + subscriptions."""
    path = _store_path()
    if path is None:
        return
    payload: dict[str, Any] = {
        "version": _PERSIST_VERSION,
        "invoices": _INVOICES,
        "subscriptions": _SUBSCRIPTIONS,
    }
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        logger.error("Failed to persist subscription store %s: %s", path, exc)
