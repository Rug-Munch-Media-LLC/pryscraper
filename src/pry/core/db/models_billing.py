"""Pry - SQLAlchemy models: billing & commerce domain.

Balances, ledger, hosting, x402 records. MIT - see LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# pyright: basic
from __future__ import annotations

from pry.core.db.models_base import Base, _now
from pry.core.db.models_invoices import HostingInvoice, InvoiceNumberSequence  # noqa: F401

# Re-exported above so the public surface (and metadata registration) is unchanged.

if Base is not None:
    from sqlalchemy import (
        JSON,
        Boolean,
        Column,
        DateTime,
        Float,
        ForeignKey,
        Index,
        Integer,
        Numeric,
        String,
        Text,
        text,
    )

    # ── Billing (prepaid balances for API-key customers) ──
    class Balance(Base):
        __tablename__ = "balances"
        user_id = Column(String(64), ForeignKey("users.user_id"), primary_key=True)
        # NUMERIC(18,6) is the only money type in the ledger path.
        balance_usd = Column(Numeric(18, 6), default=0, nullable=False)
        low_balance_threshold_usd = Column(Numeric(18, 6), default=5, nullable=False)
        updated_at = Column(DateTime, default=_now, onupdate=_now)

    class LedgerEntry(Base):
        __tablename__ = "ledger_entries"
        id = Column(Integer, primary_key=True)
        user_id = Column(String(64), ForeignKey("users.user_id"), index=True, nullable=False)
        delta_usd = Column(Numeric(18, 6), nullable=False)  # +credit / -debit
        reason = Column(String(32), nullable=False)  # deposit, grant, usage, refund
        reference = Column(String(128), default="")  # payment_id / tx_hash / key_id
        balance_after = Column(Numeric(18, 6), nullable=False)
        created_at = Column(DateTime, default=_now, index=True)
        Index("ix_ledger_user_created", user_id, created_at.desc())
        Index("ix_ledger_entries_reference", reference)
        # One row per idempotency key; blank reference (usage) is excluded.
        Index(
            "ux_ledger_user_reason_reference",
            user_id,
            reason,
            reference,
            unique=True,
            sqlite_where=text("reference <> ''"),
            postgresql_where=text("reference <> ''"),
        )

    # ── Cloud hosting (hosted pry instances) ──
    class HostingPlan(Base):
        __tablename__ = "hosting_plans"
        tier = Column(String(32), primary_key=True)  # pro | team | enterprise
        name = Column(String(64), nullable=False)
        price_usd_monthly = Column(Numeric(18, 6), nullable=True)  # None = custom quote
        max_concurrent_scrapes = Column(Integer, default=1, nullable=False)
        max_pages_month = Column(Integer, nullable=True)  # None = unlimited
        storage_gb = Column(Integer, default=1, nullable=False)
        features = Column(JSON, default=list)
        created_at = Column(DateTime, default=_now)

    class HostedInstance(Base):
        __tablename__ = "hosted_instances"
        id = Column(Integer, primary_key=True)
        instance_id = Column(String(64), unique=True, index=True, nullable=False)
        user_id = Column(
            String(64),
            ForeignKey("users.user_id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
        plan_tier = Column(String(32), nullable=False)  # pro | team | enterprise
        status = Column(String(16), default="active", nullable=False, index=True)
        api_key = Column(String(64), default="", nullable=False)  # api_keys.key_id reference
        created_at = Column(DateTime, default=_now, nullable=False)
        expires_at = Column(DateTime, nullable=True, index=True)
        region = Column(String(32), default="us-east", nullable=False)
        resource_limit = Column(JSON, default=dict)  # concurrency / pages / storage caps
        Index("ix_hosted_instances_user_created", user_id, created_at.desc())

    # ── Agency (white-label) ──
    class Agency(Base):
        __tablename__ = "agencies"
        id = Column(Integer, primary_key=True)
        agency_id = Column(String(64), unique=True, index=True, nullable=False)
        agency_name = Column(String(256), nullable=False)  # was 'name' in JSON
        owner_email = Column(String(256), nullable=False)
        custom_domain = Column(String(256), default="")
        brand_color = Column(String(16), default="#f59e0b")
        logo_url = Column(Text, default="")
        quota = Column(Integer, default=10000)
        active = Column(Boolean, default=True)
        created_at = Column(DateTime, default=_now)

    # ── Referrals (click/conversion tracking) ──
    class ReferralClick(Base):
        __tablename__ = "referral_clicks"
        id = Column(Integer, primary_key=True)
        click_id = Column(String(64), unique=True, index=True, nullable=False)
        provider = Column(String(64), index=True, nullable=False)
        url = Column(Text, nullable=False)
        source = Column(String(64), default="")
        user_id = Column(String(128), default="")
        ts = Column(DateTime, default=_now, index=True)
        converted = Column(Boolean, default=False)
        conversion_value_usd = Column(Float, default=0.0)

    class ReferralConversion(Base):
        __tablename__ = "referral_conversions"
        id = Column(Integer, primary_key=True)
        click_id = Column(
            String(64), ForeignKey("referral_clicks.click_id"), index=True, nullable=False
        )
        provider = Column(String(64), index=True, nullable=False)
        revenue_usd = Column(Float, default=0.0)
        notes = Column(Text, default="")
        ts = Column(DateTime, default=_now, index=True)

    class ReferralInAppUsage(Base):
        __tablename__ = "referral_in_app_usage"
        id = Column(Integer, primary_key=True)
        provider = Column(String(64), index=True, nullable=False)
        revenue_usd = Column(Float, default=0.0)
        ts = Column(DateTime, default=_now, index=True)

    # ── Actors (Apify-style marketplace) ──
    class Actor(Base):
        __tablename__ = "actors"
        id = Column(Integer, primary_key=True)
        actor_id = Column(String(64), unique=True, index=True, nullable=False)
        name = Column(String(256), nullable=False)
        description = Column(Text, default="")
        template_id = Column(String(64), default="")
        code = Column(Text, default="")
        price_per_run = Column(Float, default=0.0)
        visibility = Column(String(16), default="private")  # private|public|unlisted
        schedule_cron = Column(String(64), default="")
        tags = Column(JSON, default=list)
        author = Column(String(128), default="")
        run_count = Column(Integer, default=0)
        revenue_usd = Column(Float, default=0.0)
        created_at = Column(DateTime, default=_now)

    # ── x402 ledger (payment + settlement records — audit item #2) ──
    class X402PaymentRecord(Base):
        __tablename__ = "x402_payment_records"
        id = Column(Integer, primary_key=True)
        payment_id = Column(String(128), index=True, nullable=False)
        tx_hash = Column(String(80), index=True, default="")
        network = Column(String(64), default="")
        asset = Column(String(32), default="")
        amount_usd = Column(Numeric(18, 6), default=0)
        required_amount_atomic = Column(String(64), default="")
        operation = Column(String(64), index=True, default="")
        verified = Column(Boolean, default=False, index=True)
        verified_at = Column(DateTime, nullable=True)
        expires_at = Column(DateTime, nullable=True, index=True)
        facilitator = Column(String(64), default="")
        caller_key = Column(String(128), default="")
        # Customer attribution (indexed for user queries; caller_key is not).
        user_id = Column(String(128), index=True, default="")
        reason = Column(Text, default="")
        record = Column(JSON, default=dict)  # full original record (lossless)
        created_at = Column(DateTime, default=_now, nullable=False, index=True)

    class X402SettlementRecord(Base):
        __tablename__ = "x402_settlement_records"
        id = Column(Integer, primary_key=True)
        settlement_key = Column(
            String(256), unique=True, index=True, nullable=False
        )  # tx:{network}:{tx_hash} | pid:{payment_id}
        payment_id = Column(String(128), index=True, nullable=False)
        # Customer attribution: the caller_key (API key) that maps to a user.
        # Migration: ALTER TABLE x402_settlement_records ADD COLUMN user_id VARCHAR(128) DEFAULT ''
        #            CREATE INDEX idx_x402_settlement_user_id ON x402_settlement_records(user_id)
        user_id = Column(String(128), index=True, default="")
        tx_hash = Column(String(80), index=True, default="")
        network = Column(String(64), default="")
        asset = Column(String(32), default="")
        amount_usd = Column(Numeric(18, 6), default=0)
        facilitator = Column(String(64), default="")
        settled_at = Column(DateTime, nullable=True)
        receipt = Column(JSON, default=dict)  # full settlement receipt (lossless)
        success = Column(Boolean, default=True, index=True)
        created_at = Column(DateTime, default=_now, nullable=False, index=True)
