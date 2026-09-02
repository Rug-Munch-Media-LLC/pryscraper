"""Pry - SQLAlchemy ORM models.

Each model corresponds to a former JSON store (see the docstring on the
top-level ``db`` package for the mapping). This module owns the
``DeclarativeBase`` subclass and every live table.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# pyright: basic
from __future__ import annotations

from datetime import UTC, datetime

try:
    from sqlalchemy import (
        JSON,
        Boolean,
        Column,
        DateTime,
        Float,
        ForeignKey,
        Index,
        Integer,
        String,
        Text,
    )
    from sqlalchemy.orm import DeclarativeBase

    _HAS_SA = True
except ImportError:  # pragma: no cover
    _HAS_SA = False

if _HAS_SA:

    class Base(DeclarativeBase):
        pass

    def _now() -> datetime:
        return datetime.now(UTC)

    # ── Quality ──
    class QualityCheck(Base):
        __tablename__ = "quality_checks"
        id = Column(Integer, primary_key=True)
        extraction_id = Column(String(64), index=True, nullable=False)
        url = Column(Text, nullable=False)
        completeness = Column(Float, default=0.0)
        accuracy = Column(Float, default=0.0)
        freshness = Column(Float, default=0.0)
        overall_score = Column(Float, default=0.0)
        risk_level = Column(String(16), default="unknown")
        issues = Column(JSON, default=list)
        checked_at = Column(DateTime, default=_now, index=True)
        data = Column(JSON, default=dict)

    # ── Reviews (human review queue) ──
    # (ReviewItem removed 2026-08-14: zero live consumers, table dropped in 0002)

    # ── Intel (competitive intelligence snapshots) ──
    class IntelSnapshot(Base):
        __tablename__ = "intel_snapshots"
        id = Column(Integer, primary_key=True)
        competitor_id = Column(String(64), index=True, nullable=False)
        competitor_name = Column(String(256), nullable=False)
        url = Column(Text, nullable=False)
        fields = Column(JSON, default=dict)
        ts = Column(DateTime, default=_now, index=True)
        Index("ix_intel_competitor_ts", competitor_id, ts.desc())

    # ── Costing ──
    # (CostingEntry removed 2026-08-14: zero live consumers, table dropped in 0002)

    # ── Freshness ──
    # (FreshnessSnapshot removed 2026-08-14: zero live consumers, table dropped in 0002)

    # ── Structure (page structure monitor) ──
    class StructureSnapshot(Base):
        __tablename__ = "structure_snapshots"
        id = Column(Integer, primary_key=True)
        url = Column(Text, index=True, nullable=False)
        url_hash = Column(String(64), default="", index=True)
        template_id = Column(String(128), default="", index=True)
        structure_hash = Column(String(64), default="")
        selectors = Column(JSON, default=list)
        all_matched = Column(Boolean, default=False)
        matched_count = Column(Integer, default=0)
        failed_count = Column(Integer, default=0)
        changes = Column(JSON, default=list)
        change_count = Column(Integer, default=0)
        has_changes = Column(Boolean, default=False)
        dom_summary = Column(JSON, default=dict)
        checked_at = Column(DateTime, default=_now, index=True)

    # ── SEO ──
    # (SeoSnapshot removed 2026-08-14: zero live consumers, table dropped in 0002)

    # ── Monitors ──
    class Monitor(Base):
        __tablename__ = "monitors"
        id = Column(Integer, primary_key=True)
        monitor_id = Column(String(64), unique=True, index=True, nullable=False)
        url = Column(Text, nullable=False)
        monitor_name = Column(String(256), default="")  # was 'name' in JSON
        schedule_cron = Column(String(64), default="")
        check_type = Column(String(32), default="content")
        goal = Column(Text, default="")
        use_llm_judge = Column(Boolean, default=False)
        active = Column(Boolean, default=True, index=True)
        webhook_url = Column(Text, default="")
        last_check_at = Column(DateTime, nullable=True)
        last_run_at = Column(DateTime, nullable=True)
        current_version = Column(Integer, default=0)
        last_content = Column(Text, default="")
        total_checks = Column(Integer, default=0)
        total_changes = Column(Integer, default=0)
        created_at = Column(DateTime, default=_now)

    class MonitorRun(Base):
        __tablename__ = "monitor_runs"
        id = Column(Integer, primary_key=True)
        monitor_id = Column(
            String(64), ForeignKey("monitors.monitor_id"), index=True, nullable=False
        )
        ts = Column(DateTime, default=_now, index=True)
        status = Column(String(16), default="success", nullable=False)  # success|changed|error
        diff = Column(JSON, default=dict)
        error = Column(Text, default="")

    # ── Accounts (account pool for signup automation) ──
    class Account(Base):
        __tablename__ = "accounts"
        id = Column(Integer, primary_key=True)
        account_id = Column(String(64), unique=True, index=True, nullable=False)
        service = Column(String(64), index=True, nullable=False)
        username = Column(String(256), nullable=False)
        email = Column(String(256), default="")
        status = Column(String(16), default="active", nullable=False)  # active|cooldown|disabled
        used_count = Column(Integer, default=0)
        last_used_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, default=_now)

    # ── Browser sessions ──
    class BrowserSession(Base):
        __tablename__ = "browser_sessions"
        id = Column(Integer, primary_key=True)
        session_id = Column(String(64), unique=True, index=True, nullable=False)
        cookies = Column(JSON, default=list)
        local_storage = Column(JSON, default=dict)
        user_agent = Column(String(512), default="", nullable=False)
        proxy = Column(String(256), default="")
        created_at = Column(DateTime, default=_now)
        expires_at = Column(DateTime, nullable=True)

    # ── Reports ──
    class Report(Base):
        __tablename__ = "reports"
        id = Column(Integer, primary_key=True)
        report_id = Column(String(64), unique=True, index=True, nullable=False)
        report_name = Column(String(256), default="")  # was 'name' in JSON
        report_type = Column(String(64), default="html")  # html|pdf|csv
        url = Column(Text, default="")
        data = Column(JSON, default=dict)
        generated_at = Column(DateTime, default=_now, index=True)

    # ── Training datasets ──
    # (TrainingDataset removed 2026-08-14: zero live consumers, table dropped in 0002)

    # ── Pipelines ──
    class Pipeline(Base):
        __tablename__ = "pipelines"
        id = Column(Integer, primary_key=True)
        pipeline_id = Column(String(64), unique=True, index=True, nullable=False)
        pipeline_name = Column(String(256), default="")  # was 'name' in JSON
        steps = Column(JSON, default=list)
        schedule_cron = Column(String(64), default="")
        active = Column(Boolean, default=True)
        created_at = Column(DateTime, default=_now)

    # (PipelineRun removed 2026-08-14: zero live consumers, table dropped in 0002)

    # ── GDPR ──
    # (GdprRequest removed 2026-08-14: zero live consumers, table dropped in 0002)

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

    # (AgencyClient removed 2026-08-14: zero live consumers, table dropped in 0002)

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

    # (ActorRun removed 2026-08-14: zero live consumers, table dropped in 0002)

    # ── LLM usage tracking ──
    # (LlmUsage removed 2026-08-14: zero live consumers, table dropped in 0002)

    # ── Webhooks ──
    class Webhook(Base):
        __tablename__ = "webhooks"
        id = Column(Integer, primary_key=True)
        webhook_id = Column(String(64), unique=True, index=True, nullable=False)
        url = Column(Text, nullable=False)
        events = Column(JSON, default=list)
        secret = Column(String(128), default="")
        active = Column(Boolean, default=True)
        created_at = Column(DateTime, default=_now)

    # ── x402 receipts ──
    # (X402Receipt removed 2026-08-14: zero live consumers, table dropped in 0002)

    # ── Auth (Users, API Keys, Usage, Scrape Jobs) ──
    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)
        user_id = Column(String(64), unique=True, index=True, nullable=False)
        email = Column(String(256), unique=True, index=True, nullable=False)
        password_hash = Column(String(256), nullable=False)
        tier = Column(String(32), default="FREE", nullable=False)  # FREE, PRO, ENTERPRISE
        role = Column(String(32), default="USER", nullable=False)  # USER, ADMIN
        wallet = Column(String(128), default="", nullable=False)
        is_active = Column(Boolean, default=True, index=True, nullable=False)
        is_verified = Column(Boolean, default=False, nullable=False)
        created_at = Column(DateTime, default=_now, nullable=False)
        updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
        last_login_at = Column(DateTime, nullable=True)

    class APIKey(Base):
        __tablename__ = "api_keys"
        id = Column(Integer, primary_key=True)
        key_id = Column(String(64), unique=True, index=True, nullable=False)
        key_hash = Column(String(128), unique=True, index=True, nullable=False)
        key_prefix = Column(String(16), nullable=False)  # pry_abc123...
        user_id = Column(
            String(64),
            ForeignKey("users.user_id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
        name = Column(String(128), default="", nullable=False)
        scopes = Column(JSON, default=list)  # ["scrape", "crawl", "x402", "admin"]
        rate_limit_rpm = Column(Integer, default=120, nullable=False)
        quota_monthly = Column(Integer, default=10000, nullable=False)
        is_active = Column(Boolean, default=True, index=True, nullable=False)
        expires_at = Column(DateTime, nullable=True)
        last_used_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, default=_now, nullable=False)

    class Usage(Base):
        __tablename__ = "usage"
        id = Column(Integer, primary_key=True)
        user_id = Column(
            String(64),
            ForeignKey("users.user_id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
        api_key_id = Column(
            String(64),
            ForeignKey("api_keys.key_id", ondelete="SET NULL"),
            index=True,
            nullable=True,
        )
        operation = Column(String(64), index=True, nullable=False)  # scrape, crawl, extract, etc.
        endpoint = Column(String(128), default="", nullable=False)
        status = Column(
            String(16), default="success", nullable=False
        )  # success, error, rate_limited
        duration_ms = Column(Integer, default=0, nullable=False)
        bytes_in = Column(Integer, default=0, nullable=False)
        bytes_out = Column(Integer, default=0, nullable=False)
        cost_usd = Column(Float, default=0.0, nullable=False)
        ip = Column(String(64), default="", nullable=False)
        user_agent = Column(String(512), default="", nullable=False)
        error_message = Column(Text, default="", nullable=False)
        created_at = Column(DateTime, default=_now, index=True, nullable=False)
        Index("ix_usage_user_created", user_id, created_at.desc())
        Index("ix_usage_operation_created", operation, created_at.desc())

    class ScrapeJob(Base):
        __tablename__ = "scrape_jobs"
        id = Column(Integer, primary_key=True)
        job_id = Column(String(64), unique=True, index=True, nullable=False)
        user_id = Column(
            String(64),
            ForeignKey("users.user_id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
        api_key_id = Column(
            String(64),
            ForeignKey("api_keys.key_id", ondelete="SET NULL"),
            index=True,
            nullable=True,
        )
        operation = Column(String(64), nullable=False)  # scrape, crawl, batch, extract, etc.
        status = Column(
            String(32), default="pending", nullable=False
        )  # pending, running, completed, failed, cancelled
        input_data = Column(JSON, default=dict, nullable=False)  # URLs, options, schema
        result_data = Column(JSON, default=dict, nullable=False)  # content, metadata, errors
        progress = Column(Float, default=0.0, nullable=False)  # 0.0 to 1.0
        total_urls = Column(Integer, default=0, nullable=False)
        completed_urls = Column(Integer, default=0, nullable=False)
        failed_urls = Column(Integer, default=0, nullable=False)
        error_message = Column(Text, default="", nullable=False)
        started_at = Column(DateTime, nullable=True)
        completed_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, default=_now, index=True, nullable=False)
        updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
        Index("ix_scrape_jobs_user_status", user_id, status)
        Index("ix_scrape_jobs_created", created_at.desc())

    # ── Billing (prepaid balances for API-key customers) ──
    class Balance(Base):
        __tablename__ = "balances"
        user_id = Column(String(64), ForeignKey("users.user_id"), primary_key=True)
        balance_usd = Column(Float, default=0.0, nullable=False)
        low_balance_threshold_usd = Column(Float, default=5.0, nullable=False)
        updated_at = Column(DateTime, default=_now, onupdate=_now)

    class LedgerEntry(Base):
        __tablename__ = "ledger_entries"
        id = Column(Integer, primary_key=True)
        user_id = Column(String(64), ForeignKey("users.user_id"), index=True, nullable=False)
        delta_usd = Column(Float, nullable=False)  # +credit / -debit
        reason = Column(String(32), nullable=False)  # deposit, grant, usage, refund
        reference = Column(String(128), default="")  # payment_id / tx_hash / key_id
        balance_after = Column(Float, nullable=False)
        created_at = Column(DateTime, default=_now, index=True)
        Index("ix_ledger_user_created", user_id, created_at.desc())

    # ── Cloud hosting (hosted pry instances) ──
    class HostingPlan(Base):
        __tablename__ = "hosting_plans"
        tier = Column(String(32), primary_key=True)  # pro | team | enterprise
        name = Column(String(64), nullable=False)
        price_usd_monthly = Column(Float, nullable=True)  # None = custom quote
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
        status = Column(
            String(16), default="active", nullable=False, index=True
        )  # active | suspended | cancelled
        api_key = Column(String(64), default="", nullable=False)  # api_keys.key_id reference
        created_at = Column(DateTime, default=_now, nullable=False)
        expires_at = Column(DateTime, nullable=True, index=True)
        region = Column(String(32), default="us-east", nullable=False)
        resource_limit = Column(JSON, default=dict)  # concurrency / pages / storage caps
        Index("ix_hosted_instances_user_created", user_id, created_at.desc())

    # ── Hosting invoices (revenue records — persisted, audit item #1) ──
    class HostingInvoice(Base):
        __tablename__ = "hosting_invoices"
        id = Column(Integer, primary_key=True)
        invoice_id = Column(String(64), unique=True, index=True, nullable=False)
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
        amount_usd = Column(Float, nullable=False)
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
        created_at = Column(DateTime, default=_now, nullable=False)
        updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
        Index("ix_hosting_invoices_user_created", user_email, created_at.desc())

else:  # pragma: no cover
    Base = None  # type: ignore
