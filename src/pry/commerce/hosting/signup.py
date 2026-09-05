# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hosting invoice creation: signup 402 manifests, proof submission, renewals.

Builds spec-compliant x402 ``PaymentRequired`` bodies quoting the configured
treasury as ``payToAddress`` (FAIL CLOSED — never a placeholder payTo).

Wallet constants (``X402_WALLET`` / ``X402_NETWORK_WALLETS``) are read
dynamically through the hosting package so tests can monkeypatch
``hosting.X402_WALLET`` / ``hosting.X402_NETWORK_WALLETS``.
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import timedelta
from typing import Any

import pry.commerce.hosting as _hosting
from pry.commerce.hosting.errors import (
    InstanceNotFound,
    PlanNotPurchasable,
    WalletUnconfigured,
)
from pry.commerce.hosting.persistence import (
    _invoice_ttl_seconds,
    _load_invoice,
    _now,
    _save_invoice,
    _utc_iso,
)
from pry.commerce.hosting.plans import get_plan
from pry.commerce.hosting.provisioning import _ensure_user_by_email
from pry.core.db import models as _models
from pry.core.db.session import session_scope
from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    resolve_pay_to,
    wallet_configured,
)
from pry.payments.x402.scheme import (
    X402Scheme,
    asset_to_atomic,
    build_payment_required,
    normalize_network_id,
)

logger = logging.getLogger("pry.commerce.hosting")


def _public_base_url() -> str:
    """Canonical public base URL for payment-manifest resource fields.

    Env override PRY_PUBLIC_BASE_URL; defaults to the production API. The
    resource URL is what agents see in the 402 manifest — it must point at
    a domain we actually serve (pry.dev was a placeholder we do not own).
    """
    return os.getenv("PRY_PUBLIC_BASE_URL", "https://api.pryscraper.com").rstrip("/")


# ── Invoice creation ────────────────────────────────────────────────────────
def create_hosting_signup(user_email: str, plan_tier: str) -> dict[str, Any]:
    """Create a hosting signup invoice (x402 402 challenge) for *plan_tier*.

    Returns ``{invoice_id, plan_tier, amount_usd, amount_atomic, chain,
    pay_to, asset, expires_at, payment_method, payment_required}`` where
    ``payment_required`` is the spec-compliant x402 ``PaymentRequired`` body
    quoting the treasury payTo. Raises:

    - :class:`PlanNotFound` — unknown tier
    - :class:`PlanNotPurchasable` — tier without a fixed monthly price
    - :class:`WalletUnconfigured` — no real receiving wallet (FAIL CLOSED)
    """
    plan = get_plan(plan_tier)
    if not plan.is_purchasable:
        raise PlanNotPurchasable(
            f"plan '{plan.tier}' has no fixed monthly price — contact sales for a custom quote"
        )
    user_id = _ensure_user_by_email(user_email)

    asset = X402_DEFAULT_ASSET
    network = X402_DEFAULT_NETWORK
    chain = normalize_network_id(network)
    amount_atomic = asset_to_atomic(plan.price_usd_monthly, asset, network)
    pay_to = resolve_pay_to(
        chain, wallets=_hosting.X402_NETWORK_WALLETS, evm_wallet=_hosting.X402_WALLET
    )
    if not wallet_configured(pay_to):
        raise WalletUnconfigured(
            f"no real receiving wallet configured for network '{chain}' — "
            "refusing to emit a placeholder payTo"
        )

    invoice_id = f"host_{uuid.uuid4().hex[:12]}"
    resource = f"{_public_base_url()}/api/hosting/signup/{invoice_id}"
    description = f"Pry hosted instance — {plan.name} plan (${plan.price_usd_monthly}/mo)"

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
                "operation": "hosting_signup",
                "plan_tier": plan.tier,
                "invoice_id": invoice_id,
                "priceUsd": plan.price_usd_monthly,
            },
        }
    ]
    body = build_payment_required(
        "hosting_signup",
        resource=resource,
        accepts=accepts,
        description=description,
    )
    expires_at = _utc_iso(_now() + timedelta(seconds=_invoice_ttl_seconds()))

    record: dict[str, Any] = {
        "invoice_id": invoice_id,
        "kind": "signup",
        "plan_tier": plan.tier,
        "user_email": user_email.strip().lower(),
        "user_id": user_id,
        "instance_id": "",
        "payment_method": "x402",
        "amount_usd": plan.price_usd_monthly,
        "amount_atomic": amount_atomic,
        "chain": chain,
        "pay_to": pay_to,
        "asset": asset,
        "expires_at": expires_at,
        "status": "pending",
        "payment": {
            "payment_id": invoice_id,
            "network": chain,
            "asset": asset,
            "amount_usd": plan.price_usd_monthly,
            "tx_hash": None,
            "authorization": None,
        },
        "x402_body": body,
        # Email verification (audit item #4): 6-char URL-safe code proving
        # the signup email is controlled by the payer before provisioning.
        "verification_code": secrets.token_hex(3),  # 6 hex chars, URL-safe
        "email_verified": False,
    }
    _save_invoice(record)
    logger.info(
        "hosting_signup_invoice_created",
        extra={"invoice_id": invoice_id, "plan_tier": plan.tier, "user_id": user_id},
    )
    # Verification email: best-effort like the receipt — a mail outage must
    # never fail invoice creation. The code is exposed in the API response
    # ONLY when the mail backend is unconfigured (dev fallback).
    verification_code: str | None = None
    try:
        from pry.commerce.hosting.checkout import (
            mail_configured,
            send_hosting_verification_email,
        )

        if mail_configured():
            send_hosting_verification_email(
                to_email=str(record["user_email"]),
                invoice_id=invoice_id,
                code=str(record["verification_code"]),
            )
        else:
            verification_code = str(record["verification_code"])
            logger.warning(
                "hosting_verification_email_skipped_unconfigured",
                extra={"invoice_id": invoice_id},
            )
    except Exception as e:  # noqa: BLE001 — verification mail is best-effort
        logger.warning("hosting_verification_email_error", extra={"error": str(e)[:120]})
    return {
        "invoice_id": invoice_id,
        "plan_tier": plan.tier,
        "user_id": user_id,
        "amount_usd": plan.price_usd_monthly,
        "amount_atomic": amount_atomic,
        "chain": chain,
        "pay_to": pay_to,
        "asset": asset,
        "expires_at": expires_at,
        "payment_method": "x402",
        "payment_required": body,
        "email_verified": False,
        "verification_code": verification_code,
    }


def submit_hosting_payment(
    invoice_id: str,
    tx_hash: str,
    network: str = "",
    asset: str = "",
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach the payer's on-chain tx (and optional EIP-3009 authorization).

    Companion step between checkout and :func:`confirm_hosting_payment`.
    Raises ``ValueError`` for unknown invoices or empty tx hashes.
    """
    if not tx_hash or not tx_hash.strip():
        raise ValueError("tx_hash must be a non-empty transaction hash")
    invoice = _load_invoice(invoice_id)
    if invoice is None:
        raise ValueError(f"unknown hosting invoice {invoice_id!r}")
    payment = dict(invoice["payment"] or {})
    payment["tx_hash"] = tx_hash.strip()
    if network:
        payment["network"] = normalize_network_id(network)
    if asset:
        payment["asset"] = asset.upper()
    if authorization is not None:
        payment["authorization"] = authorization
    with session_scope() as session:
        row = session.query(_models.HostingInvoice).filter_by(invoice_id=invoice_id).first()
        if row is not None:
            row.payment = payment
            row.status = "submitted"
    return {**invoice, "payment": payment, "status": "submitted"}


def get_hosting_invoice(invoice_id: str) -> dict[str, Any]:
    """Return a hosting invoice record (checkout page + portal lookups)."""
    invoice = _load_invoice(invoice_id)
    if invoice is None:
        raise ValueError(f"unknown hosting invoice {invoice_id!r}")
    return invoice


def renew_instance(instance_id: str) -> dict[str, Any]:
    """Generate a new x402 invoice for renewing *instance_id*.

    The returned invoice is bound to the instance (``kind=renewal``); its
    :func:`confirm_hosting_payment` extends the expiry instead of provisioning
    a new instance. Raises :class:`InstanceNotFound` / :class:`WalletUnconfigured`.
    """
    with session_scope() as session:
        row = session.query(_models.HostedInstance).filter_by(instance_id=instance_id).first()
        if row is None:
            raise InstanceNotFound(f"unknown hosted instance {instance_id!r}")
        user_id = str(row.user_id)
        plan_tier = str(row.plan_tier)
    plan = get_plan(plan_tier)
    if not plan.is_purchasable:
        raise PlanNotPurchasable(
            f"plan '{plan.tier}' has no fixed monthly price — contact sales for a custom quote"
        )

    chain = normalize_network_id(X402_DEFAULT_NETWORK)
    amount_atomic = asset_to_atomic(plan.price_usd_monthly, X402_DEFAULT_ASSET, chain)
    pay_to = resolve_pay_to(
        chain, wallets=_hosting.X402_NETWORK_WALLETS, evm_wallet=_hosting.X402_WALLET
    )
    if not wallet_configured(pay_to):
        raise WalletUnconfigured(
            f"no real receiving wallet configured for network '{chain}' — "
            "refusing to emit a placeholder payTo"
        )

    invoice_id = f"host_{uuid.uuid4().hex[:12]}"
    resource = f"{_public_base_url()}/api/hosting/renew/{invoice_id}"
    description = f"Pry hosted instance renewal — {plan.name} plan (${plan.price_usd_monthly}/mo)"
    accepts: list[dict[str, Any]] = [
        {
            "scheme": X402Scheme.EXACT.value,
            "network": chain,
            "maxAmountRequired": str(amount_atomic),
            "resource": resource,
            "description": description,
            "mimeType": "application/json",
            "payToAddress": pay_to,
            "asset": X402_DEFAULT_ASSET,
            "extra": {
                "name": X402_DEFAULT_ASSET,
                "version": "2",
                "operation": "hosting_renewal",
                "plan_tier": plan.tier,
                "instance_id": instance_id,
                "invoice_id": invoice_id,
                "priceUsd": plan.price_usd_monthly,
            },
        }
    ]
    body = build_payment_required(
        "hosting_renewal",
        resource=resource,
        accepts=accepts,
        description=description,
    )
    record: dict[str, Any] = {
        "invoice_id": invoice_id,
        "kind": "renewal",
        "plan_tier": plan.tier,
        "user_id": user_id,
        "instance_id": instance_id,
        "payment_method": "x402",
        "amount_usd": plan.price_usd_monthly,
        "amount_atomic": amount_atomic,
        "chain": chain,
        "pay_to": pay_to,
        "asset": X402_DEFAULT_ASSET,
        "expires_at": _utc_iso(_now() + timedelta(seconds=_invoice_ttl_seconds())),
        "status": "pending",
        "payment": {
            "payment_id": invoice_id,
            "network": chain,
            "asset": X402_DEFAULT_ASSET,
            "amount_usd": plan.price_usd_monthly,
            "tx_hash": None,
            "authorization": None,
        },
        "x402_body": body,
    }
    _save_invoice(record)
    logger.info(
        "hosting_renewal_invoice_created",
        extra={"invoice_id": invoice_id, "instance_id": instance_id},
    )
    return {
        "invoice_id": invoice_id,
        "instance_id": instance_id,
        "plan_tier": plan.tier,
        "amount_usd": plan.price_usd_monthly,
        "amount_atomic": amount_atomic,
        "chain": chain,
        "pay_to": pay_to,
        "asset": X402_DEFAULT_ASSET,
        "expires_at": record["expires_at"],
        "payment_method": "x402",
        "payment_required": body,
    }
