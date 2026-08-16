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

from billing.enforcer import BillingEnforcer
from billing.subscription import (
    activate_subscription,
    create_subscription_invoice,
    reset_subscription_state,
    set_subscription_store_path,
    submit_subscription_payment,
    subscription_status,
    verify_subscription_payment,
)
from billing.tiers import DEFAULT_TIER, TIER_NAMES, TIERS, Tier, get_tier

__all__ = [
    "DEFAULT_TIER",
    "TIERS",
    "TIER_NAMES",
    "BillingEnforcer",
    "Tier",
    "activate_subscription",
    "create_subscription_invoice",
    "get_tier",
    "reset_subscription_state",
    "set_subscription_store_path",
    "submit_subscription_payment",
    "subscription_status",
    "verify_subscription_payment",
]
