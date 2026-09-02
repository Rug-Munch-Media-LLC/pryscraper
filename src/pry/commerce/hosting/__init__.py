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

NOTES / REVIEW
--------------
- Invoices are tracked in-memory (same contract as ``billing.packs`` /
  ``billing.subscription``); call :func:`reset_hosting_state` in tests.
- The self-facilitator is overridable in tests by monkeypatching
  ``hosting._get_self_facilitator``.
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

import asyncio
import calendar
import hashlib
import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pry.commerce import billing_service
from pry.core.db import models as _models
from pry.core.db.session import get_session, session_scope
from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    X402_NETWORK_WALLETS,
    X402_WALLET,
    resolve_pay_to,
    wallet_configured,
)
from pry.payments.x402.scheme import (
    X402Scheme,
    asset_to_atomic,
    build_payment_required,
    normalize_network_id,
)
from pry.payments.x402.self_facilitator import SelfFacilitator


def _public_base_url() -> str:
    """Canonical public base URL for payment-manifest resource fields.

    Env override PRY_PUBLIC_BASE_URL; defaults to the production API. The
    resource URL is what agents see in the 402 manifest — it must point at
    a domain we actually serve (pry.dev was a placeholder we do not own).
    """
    import os

    return os.getenv("PRY_PUBLIC_BASE_URL", "https://api.pryscraper.com").rstrip("/")


logger = logging.getLogger(__name__)

#: Invoice validity in seconds (default 24h).
ENV_HOSTING_INVOICE_TTL: str = "PRY_HOSTING_INVOICE_TTL"
_DEFAULT_INVOICE_TTL: int = 86_400


# ── Invoice persistence (hosting_invoices table — audit item #1) ────────────
def _invoice_to_dict(row: Any) -> dict[str, Any]:
    """Serialize a HostingInvoice row to the public invoice dict."""
    return {
        "invoice_id": row.invoice_id,
        "kind": row.kind,
        "plan_tier": row.plan_tier,
        "user_email": row.user_email,
        "user_id": row.user_id,
        "instance_id": row.instance_id or "",
        "payment_method": row.payment_method,
        "amount_usd": row.amount_usd,
        "amount_atomic": row.amount_atomic,
        "chain": row.chain,
        "pay_to": row.pay_to,
        "asset": row.asset,
        "expires_at": _utc_iso(_aware(row.expires_at)),
        "status": row.status,
        "credited_reference": row.credited_reference or "",
        "payment": dict(row.payment or {}),
        "x402_body": dict(row.x402_body or {}),
        "email_verified": bool(row.email_verified),
        "created_at": _utc_iso(_aware(row.created_at)),
    }


def _save_invoice(record: dict[str, Any]) -> None:
    """Insert or update a hosting invoice row from a record dict."""
    with session_scope() as session:
        row = (
            session.query(_models.HostingInvoice).filter_by(invoice_id=record["invoice_id"]).first()
        )
        if row is None:
            row = _models.HostingInvoice(invoice_id=record["invoice_id"])
            session.add(row)
        row.kind = str(record.get("kind", "signup"))
        row.plan_tier = str(record["plan_tier"])
        user_email = str(record.get("user_email") or "")
        if not user_email and record.get("user_id"):
            urow = session.query(_models.User).filter_by(user_id=str(record["user_id"])).first()
            user_email = str(urow.email) if urow is not None else ""
        row.user_email = user_email
        row.user_id = str(record.get("user_id") or "")
        row.instance_id = str(record.get("instance_id") or "")
        row.payment_method = str(record.get("payment_method", "x402"))
        row.amount_usd = float(record["amount_usd"])
        row.amount_atomic = str(record.get("amount_atomic", "0"))
        row.chain = str(record.get("chain", ""))
        row.pay_to = str(record.get("pay_to", ""))
        row.asset = str(record.get("asset", ""))
        row.status = str(record.get("status", "pending"))
        row.expires_at = _parse_iso(str(record["expires_at"]))
        row.payment = dict(record.get("payment") or {})
        row.x402_body = dict(record.get("x402_body") or {})
        row.verification_code = str(record.get("verification_code") or "")
        row.email_verified = bool(record.get("email_verified", False))


def _load_invoice(invoice_id: str) -> dict[str, Any] | None:
    """Fetch one invoice dict by id (None when unknown)."""
    with session_scope() as session:
        row = session.query(_models.HostingInvoice).filter_by(invoice_id=invoice_id).first()
        return _invoice_to_dict(row) if row is not None else None


def _set_invoice_fields(invoice_id: str, **fields: Any) -> None:
    """Update scalar columns on an invoice row (no-op when unknown)."""
    with session_scope() as session:
        row = session.query(_models.HostingInvoice).filter_by(invoice_id=invoice_id).first()
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)


@dataclass(frozen=True, slots=True)
class HostingPlan:
    """A hosted-instance plan with server-authoritative pricing.

    Mirrors the tier limits in :mod:`pry.commerce.billing.tiers`.
    """

    tier: str
    name: str
    price_usd_monthly: float | None
    max_concurrent_scrapes: int
    max_pages_month: int | None
    storage_gb: int
    features: list[str]

    @property
    def is_purchasable(self) -> bool:
        """True when the plan has a fixed monthly price (not a custom quote)."""
        return self.price_usd_monthly is not None


#: Canonical hosting plan catalog (matches billing.tiers pro/team/enterprise).
HOSTING_PLANS: dict[str, HostingPlan] = {
    "pro": HostingPlan(
        tier="pro",
        name="Pro",
        price_usd_monthly=49.0,
        max_concurrent_scrapes=100,
        max_pages_month=100_000,
        storage_gb=10,
        features=["priority_stealth", "residential_proxies", "standard_support"],
    ),
    "team": HostingPlan(
        tier="team",
        name="Team",
        price_usd_monthly=199.0,
        max_concurrent_scrapes=500,
        max_pages_month=500_000,
        storage_gb=50,
        features=[
            "priority_stealth",
            "residential_proxies",
            "batch",
            "custom_templates",
            "priority_support",
        ],
    ),
    "enterprise": HostingPlan(
        tier="enterprise",
        name="Enterprise",
        price_usd_monthly=None,  # custom quote
        max_concurrent_scrapes=1000,
        max_pages_month=None,  # unlimited
        storage_gb=500,
        features=["unlimited", "sla", "dedicated", "priority_support"],
    ),
}


class HostingError(Exception):
    """Base class for hosting signup errors."""


class PlanNotFound(HostingError):
    """Raised for an unknown plan tier."""


class PlanNotPurchasable(HostingError):
    """Raised when a plan has no fixed monthly price (enterprise custom quote)."""


class WalletUnconfigured(HostingError):
    """Fail-closed: no real receiving wallet is configured for the network."""


class InstanceNotFound(HostingError):
    """Raised for an unknown hosted instance id."""


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


def _invoice_ttl_seconds() -> int:
    """Invoice validity window (env override, default 24h)."""
    try:
        value = int(str(os.environ.get(ENV_HOSTING_INVOICE_TTL, _DEFAULT_INVOICE_TTL)))
        return value if value > 0 else _DEFAULT_INVOICE_TTL
    except ValueError:
        return _DEFAULT_INVOICE_TTL


# ── Plans ───────────────────────────────────────────────────────────────────
def get_plan(tier: str) -> HostingPlan:
    """Resolve *tier* to a :class:`HostingPlan`. Raises :class:`PlanNotFound`."""
    if not tier:
        raise PlanNotFound("plan tier is required")
    plan = HOSTING_PLANS.get(tier.strip().lower())
    if plan is None:
        raise PlanNotFound(f"unknown hosting plan '{tier}'")
    return plan


def list_plans() -> list[dict[str, Any]]:
    """Return the hosting plan catalog (machine-readable)."""
    return [
        {
            "tier": p.tier,
            "name": p.name,
            "price_usd_monthly": p.price_usd_monthly,
            "max_concurrent_scrapes": p.max_concurrent_scrapes,
            "max_pages_month": p.max_pages_month,
            "storage_gb": p.storage_gb,
            "features": list(p.features),
            "purchasable": p.is_purchasable,
        }
        for p in HOSTING_PLANS.values()
    ]


# ── Accounts ────────────────────────────────────────────────────────────────
def _ensure_user_by_email(user_email: str) -> str:
    """Find or create a :class:`User` row for *user_email*; return its user_id.

    Deterministic id (``host_<sha256(email)[:12]>``) so repeat signups with
    the same email resolve to the same account.
    """
    email = user_email.strip().lower()
    if not email or "@" not in email:
        raise ValueError("a valid user_email is required")
    user_id = f"host_{hashlib.sha256(email.encode()).hexdigest()[:12]}"
    with get_session() as session:
        row = session.query(_models.User).filter_by(email=email).first()
        if row is not None:
            return str(row.user_id)
        session.add(
            _models.User(
                user_id=user_id,
                email=email,
                password_hash="!",  # noqa: S106 - key-auth-only sentinel (see api_keys_service)
            )
        )
        session.commit()
        return user_id


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
    pay_to = resolve_pay_to(chain, wallets=X402_NETWORK_WALLETS, evm_wallet=X402_WALLET)
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


# ── Email verification (audit item #4) ─────────────────────────────────────
ENV_HOSTING_SKIP_EMAIL_VERIFY: str = "PRY_HOSTING_SKIP_EMAIL_VERIFY"


def _email_gate_enabled() -> bool:
    """True unless the test escape hatch disables the email gate.

    ``PRY_HOSTING_SKIP_EMAIL_VERIFY=1`` lets existing test flows confirm
    without verifying the email first (set in the hosting test fixtures).
    """
    return os.environ.get(ENV_HOSTING_SKIP_EMAIL_VERIFY, "") != "1"


def verify_hosting_email(invoice_id: str, code: str) -> dict[str, Any]:
    """Verify the signup email for *invoice_id* with *code*.

    Matches the stored verification code (constant-time compare) and marks
    the invoice ``email_verified``. Raises ``ValueError`` for unknown
    invoices; returns ``{"verified": bool}`` (False on a wrong code).
    """
    if not code or not code.strip():
        return {"verified": False, "reason": "verification code is required"}
    with session_scope() as session:
        row = session.query(_models.HostingInvoice).filter_by(invoice_id=invoice_id).first()
        if row is None:
            raise ValueError(f"unknown hosting invoice {invoice_id!r}")
        if row.email_verified:
            return {"verified": True, "invoice_id": invoice_id}
        if not secrets.compare_digest(str(row.verification_code or ""), code.strip()):
            return {"verified": False, "reason": "invalid verification code"}
        row.email_verified = True
    logger.info("hosting_email_verified", extra={"invoice_id": invoice_id})
    return {"verified": True, "invoice_id": invoice_id}


# ── Verification + settlement ───────────────────────────────────────────────
async def _verify_x402_async(invoice: dict[str, Any], *, expired: bool) -> dict[str, Any]:
    """Verify the invoice's reported tx via the self-facilitator."""
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
    verification = await _get_self_facilitator().verify(
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


def _get_self_facilitator() -> SelfFacilitator:
    """Build the self-facilitator for hosting verification.

    Overridable in tests: monkeypatch ``hosting._get_self_facilitator`` to
    return a fake exposing ``async verify`` / ``async settle``.
    """
    return SelfFacilitator(pay_to=X402_WALLET)


async def _settle_onchain_async(payment: dict[str, Any]) -> str | None:
    """Broadcast settlement via the self-facilitator. Returns tx hash or None."""
    return await _get_self_facilitator().settle(payment)


async def confirm_hosting_payment(
    invoice_id: str,
    payment_proof: str,
    *,
    network: str = "",
    asset: str = "",
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify + settle the x402 payment, then provision the hosted instance.

    ``payment_proof`` is the on-chain tx hash (plus optional EIP-3009
    ``authorization``). Flow: attach proof → verify via the self-facilitator
    → settle on-chain (funds only move on settlement success) → credit the
    prepaid ledger → provision the :class:`HostedInstance` (or extend its
    expiry for a renewal invoice) → mint an API key (signup only).

    Returns ``{paid, invoice_id, instance, api_key, tx_hash, reference}``.
    Raises ``ValueError`` for unknown invoices; a reported-but-unverified tx
    raises :class:`Underpayment` (never credited, never provisioned).
    """
    if not payment_proof or not payment_proof.strip():
        raise ValueError("payment_proof must be a non-empty transaction hash")
    invoice = _load_invoice(invoice_id)
    if invoice is None:
        raise ValueError(f"unknown hosting invoice {invoice_id!r}")
    plan_tier = str(invoice["plan_tier"])
    kind = str(invoice.get("kind", "signup"))
    user_id = str(invoice.get("user_id") or "")
    instance_id = str(invoice.get("instance_id") or "")
    amount_usd = float(invoice["amount_usd"])
    try:
        expires_at = _parse_iso(str(invoice["expires_at"]))
    except ValueError:
        expires_at = _now()
    expired = _now() >= expires_at

    # Email-verification gate (audit item #4): the portal is keyed by
    # user_email + instance id, so an unverified signup email must never
    # reach provisioning — otherwise a bad actor could sign up with someone
    # else's email and control the portal/receipt after paying. Fail closed
    # with an actionable reason. Renewal invoices are bound to an already
    # provisioned (hence verified) instance and skip the gate. [REVIEW]
    if kind == "signup" and not invoice.get("email_verified") and _email_gate_enabled():
        return {
            "paid": False,
            "invoice_id": invoice_id,
            "instance": None,
            "api_key": None,
            "reason": "email not verified — check your inbox for the verification link",
        }

    submit_hosting_payment(
        invoice_id, payment_proof, network=network, asset=asset, authorization=authorization
    )
    invoice = _load_invoice(invoice_id) or invoice
    result = await _verify_x402_async(invoice, expired=expired)
    if not result["paid"]:
        if result.get("tx_hash"):
            raise Underpayment(
                f"hosting payment not verified: {result.get('reason', 'unverified')}",
                reason=result.get("reason", "unverified"),
            )
        return {
            "paid": False,
            "invoice_id": invoice_id,
            "instance": None,
            "api_key": None,
            "reason": result.get("reason", "no payment reported"),
        }

    # ── On-chain settlement (funds move only here) ──
    payment = dict(invoice.get("payment") or {})
    settle_tx = await _settle_onchain_async(
        {
            "payment_id": invoice_id,
            "tx_hash": str(result["tx_hash"]),
            "network": str(payment.get("network") or X402_DEFAULT_NETWORK),
            "asset": str(payment.get("asset") or X402_DEFAULT_ASSET),
            "amount_usd": amount_usd,
            "authorization": payment.get("authorization"),
        }
    )
    if settle_tx is None:
        return {
            "paid": False,
            "invoice_id": invoice_id,
            "instance": None,
            "api_key": None,
            "reason": "settlement failed",
            "tx_hash": result["tx_hash"],
        }

    reference = f"hosting:{invoice_id}:{settle_tx}"
    already_credited = (invoice.get("credited_reference") or "") == reference
    if not already_credited:
        billing_service.credit(user_id, amount_usd, reason="deposit", reference=reference)
        _set_invoice_fields(invoice_id, credited_reference=reference)
    # Funds settled — the invoice is now paid.
    _set_invoice_fields(invoice_id, status="paid")

    if already_credited and instance_id:
        # Idempotent replay: the same proof already settled + provisioned.
        # Return the existing instance without re-crediting or re-provisioning.
        instance = _instance_payload(instance_id)
        api_key = None
    elif kind == "renewal" and instance_id:
        instance = _extend_instance(instance_id, months=1)
        api_key = None
    else:
        instance, api_key = _provision_instance(user_id, plan_tier)
        _set_invoice_fields(invoice_id, instance_id=instance["instance_id"])

    logger.info(
        "hosting_payment_confirmed",
        extra={
            "invoice_id": invoice_id,
            "kind": kind,
            "instance_id": instance["instance_id"] if instance else None,
            "user_id": user_id,
        },
    )

    # Human receipt: email the customer (never fails the provisioning flow).
    try:
        from pry.commerce.hosting.checkout import send_hosting_receipt

        user_email = str(invoice.get("user_email") or "")
        if user_email:
            send_hosting_receipt(
                to_email=user_email,
                invoice_id=invoice_id,
                plan_tier=plan_tier,
                amount_usd=amount_usd,
                tx_hash=str(settle_tx),
                api_key=api_key,
                instance_id=instance["instance_id"] if instance else None,
            )
    except Exception as e:  # noqa: BLE001 — receipt is best-effort
        logger.warning("hosting_receipt_error", extra={"error": str(e)[:120]})

    return {
        "paid": True,
        "invoice_id": invoice_id,
        "instance": instance,
        "api_key": api_key,  # plaintext, shown exactly once (signup only)
        "tx_hash": str(settle_tx),
        "reference": reference,
    }


class Underpayment(HostingError):
    """Raised when a reported tx does not verify — never credited/provisioned."""

    def __init__(self, message: str, *, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


def confirm_hosting_payment_sync(
    invoice_id: str,
    payment_proof: str,
    *,
    network: str = "",
    asset: str = "",
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sync bridge for :func:`confirm_hosting_payment` (``asyncio.run``).

    For CLI / tests / sync contexts. Use the async variant from a running
    event loop (FastAPI routes).
    """
    return asyncio.run(
        confirm_hosting_payment(
            invoice_id,
            payment_proof,
            network=network,
            asset=asset,
            authorization=authorization,
        )
    )


# ── Provisioning ────────────────────────────────────────────────────────────
def _provision_instance(user_id: str, plan_tier: str) -> tuple[dict[str, Any], str]:
    """Create a HostedInstance row + mint an API key. Returns (instance, plaintext)."""
    from pry.core.api_keys_service import (
        issue_key,
    )

    plan = get_plan(plan_tier)
    tier_map = {"pro": "PRO", "team": "PRO", "enterprise": "ENTERPRISE"}
    issued = issue_key(
        user_id=user_id,
        name=f"hosted-{plan.tier}",
        tier=tier_map.get(plan.tier, "PRO"),
        scopes=["scrape", "crawl", "x402"],
    )
    instance_id = f"inst_{uuid.uuid4().hex[:12]}"
    now = _now()
    resource_limit = {
        "max_concurrent_scrapes": plan.max_concurrent_scrapes,
        "max_pages_month": plan.max_pages_month,
        "storage_gb": plan.storage_gb,
    }
    with get_session() as session:
        row = _models.HostedInstance(
            instance_id=instance_id,
            user_id=user_id,
            plan_tier=plan.tier,
            status="active",
            api_key=issued["key_id"],  # reference only — never the plaintext
            created_at=now,
            expires_at=_add_months(now, 1),
            region="us-east",
            resource_limit=resource_limit,
        )
        session.add(row)
        session.commit()
    logger.info(
        "hosted_instance_provisioned",
        extra={"instance_id": instance_id, "user_id": user_id, "plan_tier": plan.tier},
    )
    return _instance_payload(instance_id), issued["plaintext"]


def _extend_instance(instance_id: str, *, months: int = 1) -> dict[str, Any]:
    """Extend a hosted instance's expiry by *months* (renewal rollover)."""
    with get_session() as session:
        row = session.query(_models.HostedInstance).filter_by(instance_id=instance_id).first()
        if row is None:
            raise InstanceNotFound(f"unknown hosted instance {instance_id!r}")
        base = row.expires_at if _aware(row.expires_at) > _now() else _now()
        row.expires_at = _add_months(base, months)
        if row.status == "suspended":
            row.status = "active"  # renewal clears a non-payment suspension
        session.commit()
    return _instance_payload(instance_id)


def _aware(dt: datetime | None) -> datetime:
    """Normalize a possibly-naive DB datetime to aware UTC."""
    if dt is None:
        return _now()
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _instance_payload(instance_id: str) -> dict[str, Any]:
    """Serialize a HostedInstance row (never exposes key material)."""
    with get_session() as session:
        row = session.query(_models.HostedInstance).filter_by(instance_id=instance_id).first()
        if row is None:
            raise InstanceNotFound(f"unknown hosted instance {instance_id!r}")
        return {
            "instance_id": row.instance_id,
            "user_id": row.user_id,
            "plan_tier": row.plan_tier,
            "status": row.status,
            "api_key_id": row.api_key,
            "created_at": _utc_iso(_aware(row.created_at)),
            "expires_at": _utc_iso(_aware(row.expires_at)),
            "region": row.region,
            "resource_limit": dict(row.resource_limit or {}),
        }


# ── Instance management ─────────────────────────────────────────────────────
def get_hosting_invoice(invoice_id: str) -> dict[str, Any]:
    """Return a hosting invoice record (checkout page + portal lookups)."""
    invoice = _load_invoice(invoice_id)
    if invoice is None:
        raise ValueError(f"unknown hosting invoice {invoice_id!r}")
    return invoice


def get_instance(instance_id: str) -> dict[str, Any]:
    """Return instance details + status. Raises :class:`InstanceNotFound`."""
    payload = _instance_payload(instance_id)
    payload["active"] = (
        payload["status"] == "active" and _aware(_parse_iso(payload["expires_at"])) > _now()
    )
    return payload


def suspend_instance(instance_id: str) -> dict[str, Any]:
    """Suspend an instance (non-payment). Idempotent."""
    with get_session() as session:
        row = session.query(_models.HostedInstance).filter_by(instance_id=instance_id).first()
        if row is None:
            raise InstanceNotFound(f"unknown hosted instance {instance_id!r}")
        row.status = "suspended"
        session.commit()
    logger.info("hosted_instance_suspended", extra={"instance_id": instance_id})
    return _instance_payload(instance_id)


def cancel_instance(instance_id: str) -> dict[str, Any]:
    """Cancel a hosted subscription. The instance stops renewing."""
    with get_session() as session:
        row = session.query(_models.HostedInstance).filter_by(instance_id=instance_id).first()
        if row is None:
            raise InstanceNotFound(f"unknown hosted instance {instance_id!r}")
        row.status = "cancelled"
        session.commit()
    logger.info("hosted_instance_cancelled", extra={"instance_id": instance_id})
    return _instance_payload(instance_id)


def list_instances(user_id: str) -> list[dict[str, Any]]:
    """All hosted instances for *user_id* (newest first)."""
    with get_session() as session:
        rows = (
            session.query(_models.HostedInstance)
            .filter_by(user_id=user_id)
            .order_by(_models.HostedInstance.created_at.desc())
            .all()
        )
        return [
            {
                "instance_id": r.instance_id,
                "plan_tier": r.plan_tier,
                "status": r.status,
                "created_at": _utc_iso(_aware(r.created_at)),
                "expires_at": _utc_iso(_aware(r.expires_at)),
                "region": r.region,
            }
            for r in rows
        ]


def renew_instance(instance_id: str) -> dict[str, Any]:
    """Generate a new x402 invoice for renewing *instance_id*.

    The returned invoice is bound to the instance (``kind=renewal``); its
    :func:`confirm_hosting_payment` extends the expiry instead of provisioning
    a new instance. Raises :class:`InstanceNotFound` / :class:`WalletUnconfigured`.
    """
    with get_session() as session:
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
    pay_to = resolve_pay_to(chain, wallets=X402_NETWORK_WALLETS, evm_wallet=X402_WALLET)
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


def reset_hosting_state() -> None:
    """Reset the invoice registry (test/ops compat no-op).

    Invoices now live in the ``hosting_invoices`` table — they survive
    restarts by design, so there is nothing to clear in-process. Tests
    isolate via a per-test SQLite DB (see tests/conftest.py).
    """
    return None
