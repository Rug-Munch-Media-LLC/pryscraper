"""Pry — cloud hosting signup + checkout (hosted pry instances, x402 rail).

Full signup flow for hosted pry instances: a client signs up with an email,
pays the monthly plan price in crypto over Pry's own x402 self-facilitation
rail (USDC, EIP-3009 / SPL), and receives a provisioned :class:`HostedInstance`
with a minted API key. Renewal re-arms the same x402 flow; non-payment
suspends the instance.

Plans mirror :mod:`pry.commerce.billing.tiers` (pro $49/mo, team $199/mo,
enterprise custom quote). The monetary gate is the 402 payment manifest
returned by :func:`create_hosting_signup` — the HTTP control-plane routes are
classified free in ``x402_middleware.classification`` (same contract as the
billing packs / subscription routers).

Payment rail (single system, no second processor):
  1. :func:`create_hosting_signup` — build an x402 ``PaymentRequired``
      manifest quoting the plan's monthly price with the configured treasury
      as ``payToAddress`` (FAIL CLOSED — never a placeholder payTo).
  2. :func:`confirm_hosting_payment` — verify the reported tx via
      :class:`x402.self_facilitator.SelfFacilitator`, settle on-chain, credit
      the prepaid ledger (:mod:`pry.commerce.billing_service`), provision the
      :class:`HostedInstance` row and mint an API key (plaintext shown once).
  3. :func:`renew_instance` — a fresh invoice bound to the instance; its
      confirm extends ``expires_at`` instead of provisioning a new instance.

Module layout (cohesive split of the former single-file implementation):
  - :mod:`.errors` — exception hierarchy
  - :mod:`.plans` — plan catalog + pricing
  - :mod:`.persistence` — invoice rows + shared time helpers
  - :mod:`.email_verify` — signup-email verification gate
  - :mod:`.provisioning` — instance provisioning + lifecycle
  - :mod:`.signup` — invoice creation (signup / proof / renewal)
  - :mod:`.settlement` — x402 verify + settle + confirm

NOTES / REVIEW
--------------
- Invoices are tracked in the ``hosting_invoices`` table (same contract as
  ``billing.packs`` / ``billing.subscription``); call
  :func:`reset_hosting_state` in tests.
- The self-facilitator is overridable in tests by monkeypatching
  ``hosting._get_self_facilitator`` (resolved dynamically through this
  package namespace by :mod:`.settlement`).
- ``HostedInstance.api_key`` stores the minted key's ``key_id`` reference
  (never the plaintext or hash) — the plaintext is returned exactly once at
  confirm time. [REVIEW]
- Enterprise has no fixed monthly price (custom quote) — signup raises
  :class:`PlanNotPurchasable` until a quote is attached. [REVIEW]
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging

from pry.commerce.hosting.email_verify import (
    ENV_HOSTING_SKIP_EMAIL_VERIFY,
    _email_gate_enabled as _email_gate_enabled,
    verify_hosting_email,
)
from pry.commerce.hosting.errors import (
    HostingError,
    InstanceNotFound,
    PlanNotFound,
    PlanNotPurchasable,
    Underpayment,
    WalletUnconfigured,
)
from pry.commerce.hosting.persistence import (
    ENV_HOSTING_INVOICE_TTL,
    _add_months as _add_months,
    _aware as _aware,
    _invoice_ttl_seconds as _invoice_ttl_seconds,
    _load_invoice as _load_invoice,
    _now as _now,
    _parse_iso as _parse_iso,
    _save_invoice as _save_invoice,
    _set_invoice_fields as _set_invoice_fields,
    _utc_iso as _utc_iso,
    reset_hosting_state,
)
from pry.commerce.hosting.plans import (
    HOSTING_PLANS,
    HostingPlan,
    get_plan,
    list_plans,
)
from pry.commerce.hosting.provisioning import (
    _ensure_user_by_email as _ensure_user_by_email,
    _extend_instance as _extend_instance,
    _instance_payload as _instance_payload,
    _provision_instance as _provision_instance,
    cancel_instance,
    get_instance,
    list_instances,
    suspend_instance,
)
from pry.commerce.hosting.settlement import (
    _get_self_facilitator as _get_self_facilitator,
    _settle_onchain_async as _settle_onchain_async,
    _verify_x402_async as _verify_x402_async,
    confirm_hosting_payment,
    confirm_hosting_payment_sync,
)
from pry.commerce.hosting.signup import (
    _public_base_url as _public_base_url,
    create_hosting_signup,
    get_hosting_invoice,
    renew_instance,
    submit_hosting_payment,
)
from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    X402_NETWORK_WALLETS,
    X402_WALLET,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ENV_HOSTING_INVOICE_TTL",
    "ENV_HOSTING_SKIP_EMAIL_VERIFY",
    "HOSTING_PLANS",
    "X402_DEFAULT_ASSET",
    "X402_DEFAULT_NETWORK",
    "X402_NETWORK_WALLETS",
    "X402_WALLET",
    "HostingError",
    "HostingPlan",
    "InstanceNotFound",
    "PlanNotFound",
    "PlanNotPurchasable",
    "Underpayment",
    "WalletUnconfigured",
    "cancel_instance",
    "confirm_hosting_payment",
    "confirm_hosting_payment_sync",
    "create_hosting_signup",
    "get_hosting_invoice",
    "get_instance",
    "get_plan",
    "list_instances",
    "list_plans",
    "renew_instance",
    "reset_hosting_state",
    "submit_hosting_payment",
    "suspend_instance",
    "verify_hosting_email",
]
