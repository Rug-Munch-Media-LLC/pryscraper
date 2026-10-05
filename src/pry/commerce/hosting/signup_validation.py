# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Purchase-gate and x402 quote resolution for hosting invoices.

Resolves a plan tier into the pricing primitives shared by signup and
renewal invoices: the treasury ``payToAddress`` for the default network and
the atomic amount. FAILS CLOSED when no real receiving wallet is configured
— a placeholder payTo is never emitted.
"""

from __future__ import annotations

import os
from typing import Any, NamedTuple

import pry.commerce.hosting as _hosting
from pry.commerce.hosting.errors import PlanNotPurchasable, WalletUnconfigured
from pry.commerce.hosting.plans import get_plan
from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    resolve_pay_to,
    wallet_configured,
)
from pry.payments.x402.scheme import X402Scheme, asset_to_atomic, normalize_network_id


class InvoiceQuote(NamedTuple):
    """Resolved pricing primitives for one hosting invoice."""

    plan: Any
    asset: str
    chain: str
    amount_atomic: int
    pay_to: str


def _public_base_url() -> str:
    """Canonical public base URL for payment-manifest resource fields.

    Env override PRY_PUBLIC_BASE_URL; defaults to the production API. The
    resource URL is what agents see in the 402 manifest — it must point at
    a domain we actually serve (pry.dev was a placeholder we do not own).
    """
    return os.getenv("PRY_PUBLIC_BASE_URL", "https://api.pryscraper.com").rstrip("/")


def _resolve_quote(plan_tier: str) -> InvoiceQuote:
    """Resolve *plan_tier* into the x402 pricing primitives for an invoice.

    Raises :class:`PlanNotPurchasable` for a tier without a fixed monthly
    price and :class:`WalletUnconfigured` when no real wallet is configured
    for the default network.
    """
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
    return InvoiceQuote(plan, X402_DEFAULT_ASSET, chain, amount_atomic, pay_to)


def _build_signup_accepts(
    plan: Any,
    *,
    resource: str,
    invoice_id: str,
    chain: str,
    amount_atomic: int,
    pay_to: str,
    asset: str,
) -> list[dict[str, Any]]:
    """Build the single-option x402 ``accepts`` list for a signup invoice."""
    description = f"Pry hosted instance — {plan.name} plan (${plan.price_usd_monthly}/mo)"
    return [
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
