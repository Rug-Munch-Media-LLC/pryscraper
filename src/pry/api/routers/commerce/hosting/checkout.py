"""Human checkout, magic-link request, and customer portal routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Query, Response

# FastAPI evaluates postponed endpoint annotations at runtime.
from pry.api.routers.commerce.hosting.models import HostingPortalRequest  # noqa: TC001
from pry.api.routers.commerce.hosting.router import router

logger = logging.getLogger(__name__)


@router.get(
    "/v1/hosting/checkout/{invoice_id}",
    summary="Human crypto checkout page (QR + tx submission)",
    description=(
        "Self-contained HTML checkout for a hosting invoice: QR code, wallet "
        "deep-link, amount + address, network picker, and a tx-hash form that "
        "calls the existing on-chain confirm endpoint. Humans pay from any "
        "wallet; the instance provisions automatically on verification."
    ),
    include_in_schema=False,
)
async def hosting_checkout_page(invoice_id: str) -> Response:
    from pry.commerce.hosting import get_hosting_invoice
    from pry.commerce.hosting.checkout import render_checkout_page

    try:
        invoice = get_hosting_invoice(invoice_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=render_checkout_page(invoice), media_type="text/html")


@router.post(
    "/v1/hosting/portal/request",
    summary="Request a portal magic-link (emailed to the customer)",
    description=(
        "Sends a fresh signed portal link to the customer's email (rate-"
        "limited: max 5 per email per hour). The link authenticates the "
        "portal for its TTL — no API key or password needed. Always "
        "returns success (no account enumeration)."
    ),
)
async def hosting_portal_request(payload: HostingPortalRequest) -> dict[str, Any]:
    """Magic-link request flow: email a fresh signed portal token."""
    from pry.commerce.hosting import _ensure_user_by_email, list_instances
    from pry.commerce.hosting.checkout import send_portal_link_email
    from pry.commerce.hosting.portal_tokens import check_portal_link_rate

    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="a valid email is required")
    if not check_portal_link_rate(email):
        logger.warning("portal_link_rate_limited", extra={"email_hash": email[:3] + "***"})
        raise HTTPException(
            status_code=429,
            detail="too many portal link requests — try again later",
        )
    sent = False
    try:
        user_id = _ensure_user_by_email(email)
        if list_instances(user_id):
            send_portal_link_email(to_email=email)
            sent = True
    except Exception as exc:  # noqa: BLE001 — never leak account state
        logger.warning("portal_link_request_failed", extra={"error": str(exc)[:120]})
    return {"success": True, "data": {"sent": sent}}


@router.get(
    "/v1/hosting/portal",
    summary="Customer portal — instances, usage and API keys",
    description=(
        "Read-only portal for hosted customers: instances, expiry, prepaid "
        "balance and ledger. Authenticated by a signed portal token from "
        "the receipt email (magic-link) — the token encodes the customer "
        "email + expiry under an HMAC-SHA256 signature. 401 without a "
        "valid token."
    ),
)
async def hosting_portal(
    token: str = Query(..., description="Signed portal token from the receipt/magic-link email"),
) -> dict[str, Any]:
    from pry.commerce import billing_service
    from pry.commerce.hosting import _ensure_user_by_email, list_instances
    from pry.commerce.hosting.portal_tokens import verify_portal_token

    email = verify_portal_token(token)
    if email is None:
        raise HTTPException(status_code=401, detail="invalid or expired portal token")
    user_id = _ensure_user_by_email(email)
    instances = list_instances(user_id)
    balance: dict[str, Any] = {}
    ledger: list[dict[str, Any]] = []
    try:
        balance = billing_service.balance(user_id)
        ledger = billing_service.ledger(user_id, limit=25)
    except Exception as exc:  # noqa: BLE001 — portal must render without billing rows
        logger.warning("portal_billing_lookup_failed", extra={"error": str(exc)[:120]})
    usage: list[dict[str, Any]] = []
    try:
        from pry.core.api_keys_service import list_keys_for_user

        enforcer = _usage_enforcer()
        for key_row in list_keys_for_user(user_id):
            stats = enforcer.usage_stats(key_row.get("key") or key_row.get("key_prefix"))
            stats.pop("api_key", None)
            stats["key_name"] = key_row.get("name", "")
            stats["key_id"] = key_row.get("key_id", "")
            usage.append(stats)
    except Exception as exc:  # noqa: BLE001 — usage is best-effort
        logger.warning("portal_usage_lookup_failed", extra={"error": str(exc)[:120]})
    return {
        "success": True,
        "data": {
            "email": email,
            "instances": instances,
            "balance": balance,
            "ledger": ledger,
            "usage": usage,
            "support": "support@pryscraper.com",
        },
    }


def _usage_enforcer() -> Any:
    """Construct the per-call billing enforcer used for portal usage."""
    from pry.commerce.billing.enforcer import BillingEnforcer

    return BillingEnforcer()
