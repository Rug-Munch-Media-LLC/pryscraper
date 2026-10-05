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
import uuid
from datetime import timedelta
from typing import Any

from pry.commerce.hosting.errors import InstanceNotFound
from pry.commerce.hosting.persistence import (
    _invoice_ttl_seconds,
    _load_invoice,
    _now,
    _save_invoice,
    _utc_iso,
)
from pry.commerce.hosting.signup_provision import _provision_signup_invoice
from pry.commerce.hosting.signup_validation import (
    _public_base_url as _public_base_url,
    _resolve_quote,
)
from pry.core.db import models as _models
from pry.core.db.session import session_scope
from pry.payments.x402.scheme import X402Scheme, build_payment_required, normalize_network_id

logger = logging.getLogger("pry.commerce.hosting")


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
    return _provision_signup_invoice(user_email, plan_tier, verification_email=True)


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
    quote = _resolve_quote(plan_tier)

    invoice_id = f"host_{uuid.uuid4().hex[:12]}"
    resource = f"{_public_base_url()}/api/hosting/renew/{invoice_id}"
    description = (
        f"Pry hosted instance renewal — {quote.plan.name} plan (${quote.plan.price_usd_monthly}/mo)"
    )
    accepts: list[dict[str, Any]] = [
        {
            "scheme": X402Scheme.EXACT.value,
            "network": quote.chain,
            "maxAmountRequired": str(quote.amount_atomic),
            "resource": resource,
            "description": description,
            "mimeType": "application/json",
            "payToAddress": quote.pay_to,
            "asset": quote.asset,
            "extra": {
                "name": quote.asset,
                "version": "2",
                "operation": "hosting_renewal",
                "plan_tier": quote.plan.tier,
                "instance_id": instance_id,
                "invoice_id": invoice_id,
                "priceUsd": quote.plan.price_usd_monthly,
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
        "plan_tier": quote.plan.tier,
        "user_id": user_id,
        "instance_id": instance_id,
        "payment_method": "x402",
        "amount_usd": quote.plan.price_usd_monthly,
        "amount_atomic": quote.amount_atomic,
        "chain": quote.chain,
        "pay_to": quote.pay_to,
        "asset": quote.asset,
        "expires_at": _utc_iso(_now() + timedelta(seconds=_invoice_ttl_seconds())),
        "status": "pending",
        "payment": {
            "payment_id": invoice_id,
            "network": quote.chain,
            "asset": quote.asset,
            "amount_usd": quote.plan.price_usd_monthly,
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
        "plan_tier": quote.plan.tier,
        "amount_usd": quote.plan.price_usd_monthly,
        "amount_atomic": quote.amount_atomic,
        "chain": quote.chain,
        "pay_to": quote.pay_to,
        "asset": quote.asset,
        "expires_at": record["expires_at"],
        "payment_method": "x402",
        "payment_required": body,
    }
