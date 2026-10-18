"""Pry - SQLAlchemy models: hosting invoices & invoice-number sequences.

Extracted from ``models_billing`` so the invoice schema (the audit-critical
revenue record) stands alone. ``models_billing`` re-exports both classes, so
``pry.core.db.models_billing.HostingInvoice`` keeps working unchanged and the
tables stay registered on the same ``Base.metadata``.

MIT - see LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# pyright: basic
from __future__ import annotations

from pry.core.db.models_base import Base, _now

if Base is not None:
    from sqlalchemy import (
        JSON,
        Boolean,
        Column,
        DateTime,
        ForeignKey,
        Index,
        Integer,
        Numeric,
        String,
    )

    # ── Invoice number sequence (atomic, per YYYYMM) ──
    class InvoiceNumberSequence(Base):
        __tablename__ = "invoice_number_sequences"
        period = Column(String(6), primary_key=True)  # YYYYMM
        last_value = Column(Integer, default=0, nullable=False)

    # ── Hosting invoices (revenue records — persisted, audit item #1) ──
    class HostingInvoice(Base):
        __tablename__ = "hosting_invoices"
        id = Column(Integer, primary_key=True)
        invoice_id = Column(String(64), unique=True, index=True, nullable=False)
        # Human-readable INV-YYYYMM-NNNNNN; NULL until 0012 backfill/creation.
        invoice_number = Column(String(32), unique=True, index=True, nullable=True)
        # Tax is computed at creation; paid invoices are immutable.
        tax_amount = Column(Numeric(18, 6), default=0, nullable=False)
        tax_rate = Column(Numeric(9, 6), default=0, nullable=False)  # fraction, 0.20 = 20%
        tax_country = Column(String(2), default="", nullable=False)
        reverse_charge = Column(Boolean, default=False, nullable=False)
        kind = Column(String(16), default="signup", nullable=False)  # signup | renewal
        plan_tier = Column(String(32), nullable=False)  # pro | team | enterprise
        user_email = Column(String(256), index=True, nullable=False)
        user_id = Column(
            String(64),
            ForeignKey("users.user_id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
        instance_id = Column(String(64), default="", index=True)  # "" until provisioned
        payment_method = Column(String(32), default="x402", nullable=False)
        amount_usd = Column(Numeric(18, 6), nullable=False)
        # amount_atomic is the settlement source of truth; amount_usd is derived.
        amount_atomic = Column(String(64), default="0", nullable=False)
        chain = Column(String(32), default="", nullable=False)
        pay_to = Column(String(128), default="", nullable=False)
        asset = Column(String(16), default="USDC", nullable=False)
        status = Column(
            String(16), default="pending", nullable=False, index=True
        )  # pending | submitted | paid | expired
        expires_at = Column(DateTime, nullable=True, index=True)
        payment = Column(JSON, default=dict)  # tx_hash / network / asset / authorization
        x402_body = Column(JSON, default=dict)  # the 402 manifest body
        credited_reference = Column(String(256), default="")  # ledger idempotency ref
        # Email verification (audit item #4): proof-of-ownership for the
        # signup email before the payment confirm gates provisioning.
        verification_code = Column(String(16), default="", nullable=False)
        email_verified = Column(Boolean, default=False, nullable=False)
        # Wrong-code attempts; MAX_VERIFICATION_ATTEMPTS locks the invoice.
        verification_attempts = Column(Integer, default=0, nullable=False)
        created_at = Column(DateTime, default=_now, nullable=False)
        updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
        Index("ix_hosting_invoices_user_created", user_email, created_at.desc())
