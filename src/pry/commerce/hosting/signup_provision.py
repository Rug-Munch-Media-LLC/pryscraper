# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Signup provisioning: x402 body, invoice record, and verification email.

Assembles and persists a hosting signup invoice, then sends the email
verification code best-effort. The SAME code is always persisted and returned
by :func:`_send_verification_email`; the API response exposes it only when
delivery did not happen (unconfigured or failed) — a mail outage must never
fail invoice creation.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import timedelta
from typing import Any, NamedTuple

from pry.commerce.hosting.persistence import (
    _invoice_ttl_seconds,
    _now,
    _save_invoice,
    _utc_iso,
)
from pry.commerce.hosting.signup_validation import (
    InvoiceQuote,
    _build_signup_accepts,
    _public_base_url,
    _resolve_quote,
)
from pry.payments.x402.scheme import build_payment_required

logger = logging.getLogger("pry.commerce.hosting")


class _SignupDraft(NamedTuple):
    """A built signup manifest: id, resource URL, and x402 body."""

    invoice_id: str
    resource: str
    body: dict[str, Any]


def _build_signup_draft(quote: InvoiceQuote) -> _SignupDraft:
    """Build the invoice id, resource URL and x402 ``PaymentRequired`` body."""
    invoice_id = f"host_{uuid.uuid4().hex[:12]}"
    resource = f"{_public_base_url()}/api/hosting/signup/{invoice_id}"
    plan = quote.plan
    accepts = _build_signup_accepts(
        plan,
        resource=resource,
        invoice_id=invoice_id,
        chain=quote.chain,
        amount_atomic=quote.amount_atomic,
        pay_to=quote.pay_to,
        asset=quote.asset,
    )
    body = build_payment_required(
        "hosting_signup",
        resource=resource,
        accepts=accepts,
        description=f"Pry hosted instance — {plan.name} plan (${plan.price_usd_monthly}/mo)",
    )
    return _SignupDraft(invoice_id, resource, body)


def _new_signup_invoice(
    quote: InvoiceQuote,
    user_email: str,
    user_id: str,
    draft: _SignupDraft,
) -> dict[str, Any]:
    """Assemble the persistent signup invoice record."""
    plan = quote.plan
    return {
        "invoice_id": draft.invoice_id,
        "kind": "signup",
        "plan_tier": plan.tier,
        "user_email": user_email.strip().lower(),
        "user_id": user_id,
        "instance_id": "",
        "payment_method": "x402",
        "amount_usd": plan.price_usd_monthly,
        "amount_atomic": quote.amount_atomic,
        "chain": quote.chain,
        "pay_to": quote.pay_to,
        "asset": quote.asset,
        "expires_at": _utc_iso(_now() + timedelta(seconds=_invoice_ttl_seconds())),
        "status": "pending",
        "payment": {
            "payment_id": draft.invoice_id,
            "network": quote.chain,
            "asset": quote.asset,
            "amount_usd": plan.price_usd_monthly,
            "tx_hash": None,
            "authorization": None,
        },
        "x402_body": draft.body,
        # Email verification (audit item #4): 6-char URL-safe code proving
        # the signup email is controlled by the payer before provisioning.
        "verification_code": secrets.token_hex(3),  # 6 hex chars, URL-safe
        "email_delivery": "unconfigured",  # sent | unconfigured | failed | skipped
        "email_verified": False,
    }


def _send_verification_email(record: dict[str, Any]) -> str:
    """Send the verification email best-effort and return the SAME code.

    The generated code is always returned so the caller persists exactly what
    was (or would have been) emailed. Delivery outcome is stamped onto
    ``record["email_delivery"]`` as ``sent`` / ``unconfigured`` / ``failed``;
    a mail outage is logged and swallowed — it must never fail invoice
    creation.
    """
    invoice_id = str(record["invoice_id"])
    code = str(record["verification_code"])
    delivery = "unconfigured"
    try:
        from pry.commerce.hosting.checkout import (
            mail_configured,
            send_hosting_verification_email,
        )

        if mail_configured():
            send_hosting_verification_email(
                to_email=str(record["user_email"]),
                invoice_id=invoice_id,
                code=code,
            )
            delivery = "sent"
        else:
            logger.warning(
                "hosting_verification_email_skipped_unconfigured",
                extra={"invoice_id": invoice_id},
            )
    except Exception as e:  # noqa: BLE001 — verification mail is best-effort
        delivery = "failed"
        logger.warning("hosting_verification_email_error", extra={"error": str(e)[:120]})
    record["email_delivery"] = delivery
    return code


def _signup_result(quote: InvoiceQuote, record: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Shape the API response for a persisted signup invoice."""
    plan = quote.plan
    return {
        "invoice_id": record["invoice_id"],
        "plan_tier": plan.tier,
        "user_id": user_id,
        "amount_usd": plan.price_usd_monthly,
        "amount_atomic": quote.amount_atomic,
        "chain": quote.chain,
        "pay_to": quote.pay_to,
        "asset": quote.asset,
        "expires_at": record["expires_at"],
        "payment_method": "x402",
        "payment_required": record["x402_body"],
        "email_verified": bool(record["email_verified"]),
        # Only expose the code when it did not reach the mailbox: exposing a
        # code that WAS emailed would let anyone holding the API response
        # verify an address they do not control.
        "verification_code": (
            record["verification_code"] if record.get("email_delivery") != "sent" else None
        )
        or None,
        "email_delivery": record.get("email_delivery", "unconfigured"),
    }


def _provision_signup_invoice(
    email: str,
    plan_tier: str,
    *,
    verification_email: bool,
) -> dict[str, Any]:
    """Create, persist and stamp a signup invoice; return the subscription payload.

    The verification email is sent when *verification_email* is set and the
    generated code is persisted exactly as emailed (never overwritten with an
    empty string). When not set, ``email_verified`` is pre-approved.
    """
    from pry.commerce.hosting.provisioning import _ensure_user_by_email

    quote = _resolve_quote(plan_tier)
    user_id = _ensure_user_by_email(email)
    record = _new_signup_invoice(quote, email, user_id, _build_signup_draft(quote))
    if verification_email:
        # Always persists the generated code — the helper returns the SAME
        # code it emailed (the previous `or ""` made every mail-configured
        # signup impossible to verify).
        record["verification_code"] = _send_verification_email(record)
    else:
        record["verification_code"] = ""
        record["email_delivery"] = "skipped"
        record["email_verified"] = True
    _save_invoice(record)
    logger.info(
        "hosting_signup_invoice_created",
        extra={
            "invoice_id": record["invoice_id"],
            "plan_tier": quote.plan.tier,
            "user_id": user_id,
        },
    )
    return _signup_result(quote, record, user_id)
