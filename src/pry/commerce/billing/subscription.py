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

This module is a thin facade: the implementation lives in
``subscription_invoices`` / ``subscription_verify`` / ``subscription_activation``
/ ``subscription_state`` / ``subscription_time`` (same package). The patchable
hooks below (``_now``, ``_get_self_facilitator``, ``httpx``,
``build_payment_required``, ``X402_WALLET``, ``X402_NETWORK_WALLETS``) are
defined HERE and read through this module by the implementation modules, so
``monkeypatch.setattr(subscription, ...)`` keeps working.

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

from datetime import UTC, datetime
from typing import Any

import httpx  # noqa: F401  (re-exported: tests monkeypatch subscription.httpx)

from pry.payments.x402 import X402_NETWORK_WALLETS, X402_WALLET  # noqa: F401
from pry.payments.x402.scheme import build_payment_required  # noqa: F401
from pry.payments.x402.self_facilitator import SelfFacilitator

__all__ = [
    "activate_subscription",
    "create_subscription_invoice",
    "reset_subscription_state",
    "set_subscription_store_path",
    "settle_subscription_payment",
    "submit_subscription_payment",
    "subscription_status",
    "verify_subscription_payment",
]


# ── Patchable hooks (implementation modules read these via this facade) ─────
def _now() -> datetime:
    """Current UTC timestamp (single hook so tests can freeze time)."""
    return datetime.now(UTC)


def _get_self_facilitator() -> Any:
    """Build the self-facilitator used for x402 verification.

    Overridable in tests: monkeypatch ``billing.subscription._get_self_facilitator``
    to return a fake exposing ``async verify(payment) -> VerifyResult``.
    """

    return SelfFacilitator(pay_to=X402_WALLET)


# ── Re-exports (implementation modules; keep the public surface stable) ─────
from pry.commerce.billing.subscription_activation import (  # noqa: E402,F401
    _usage_for,
    activate_subscription,
    subscription_status,
)
from pry.commerce.billing.subscription_invoices import (  # noqa: E402,F401
    _DEFAULT_INVOICE_TTL,
    ENV_BTCPAY_API_KEY,
    ENV_BTCPAY_STORE,
    ENV_BTCPAY_URL,
    ENV_INVOICE_TTL,
    _btcpay_env,
    _create_btcpay_invoice,
    _create_x402_invoice,
    _extract_btcpay_address,
    _extract_btcpay_tx_hash,
    _invoice_ttl_seconds,
    _public_base_url,
    _validate_months,
    create_subscription_invoice,
    submit_subscription_payment,
)
from pry.commerce.billing.subscription_state import (  # noqa: E402,F401
    _INVOICES,
    _PERSIST_VERSION,
    _SUBSCRIPTIONS,
    ENV_SUBSCRIPTIONS_FILE,
    _configured_store_path,
    _ensure_loaded,
    _ensure_loaded_locked,
    _lock,
    _register_invoice,
    _save_state_locked,
    _store_path,
    reset_subscription_state,
    set_subscription_store_path,
)
from pry.commerce.billing.subscription_time import (  # noqa: E402,F401
    _add_months,
    _parse_iso,
    _utc_iso,
)
from pry.commerce.billing.subscription_verify import (  # noqa: E402,F401
    _settle_x402_payment_async,
    _verify_btcpay,
    _verify_x402,
    _verify_x402_payment,
    _verify_x402_payment_sync,
    settle_subscription_payment,
    verify_subscription_payment,
)
