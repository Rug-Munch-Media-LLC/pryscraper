"""Pry — subscription billing: tier table + enforcement + crypto payments.

Self-contained module for the marketing site's monthly Pro/Team/Enterprise
tiers. Importing :mod:`billing` has no side effects and requires no app
wiring: the API middleware constructs a :class:`BillingEnforcer` and calls
:meth:`BillingEnforcer.check_request` per request; the payment surface
(:func:`create_subscription_invoice` & friends) is provider-flexible
(x402 self-facilitator by default, BTCPay Server fallback).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from pry.commerce.billing.enforcer import BillingEnforcer
from pry.commerce.billing.packs import (
    PACKS,
    SCRAPE_CREDIT_USD,
    STARTER_CREDITS_USD,
    Pack,
    PackNotFound,
    PackWalletUnconfigured,
    Underpayment,
    confirm_pack_purchase,
    confirm_pack_purchase_async,
    create_pack_invoice,
    get_pack,
    list_packs,
    reset_pack_state,
    set_pack_store_path,
    signup_crypto,
    submit_pack_payment,
    verify_pack_payment,
    verify_pack_payment_async,
)
from pry.commerce.billing.subscription import (
    activate_subscription,
    create_subscription_invoice,
    reset_subscription_state,
    set_subscription_store_path,
    settle_subscription_payment,
    submit_subscription_payment,
    subscription_status,
    verify_subscription_payment,
)
from pry.commerce.billing.tiers import DEFAULT_TIER, TIER_NAMES, TIERS, Tier, get_tier

__all__ = [
    "DEFAULT_TIER",
    "PACKS",
    "SCRAPE_CREDIT_USD",
    "STARTER_CREDITS_USD",
    "TIERS",
    "TIER_NAMES",
    "BillingEnforcer",
    "Pack",
    "PackNotFound",
    "PackWalletUnconfigured",
    "Tier",
    "Underpayment",
    "activate_subscription",
    "confirm_pack_purchase",
    "confirm_pack_purchase_async",
    "create_pack_invoice",
    "create_subscription_invoice",
    "get_pack",
    "get_tier",
    "list_packs",
    "reset_pack_state",
    "reset_subscription_state",
    "set_pack_store_path",
    "set_subscription_store_path",
    "settle_subscription_payment",
    "signup_crypto",
    "submit_pack_payment",
    "submit_subscription_payment",
    "subscription_status",
    "verify_pack_payment",
    "verify_pack_payment_async",
    "verify_subscription_payment",
]
