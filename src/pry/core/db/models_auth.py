"""Pry - SQLAlchemy models: auth & usage domain.

Users, API keys, usage tracking, scrape jobs, audit log.

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

from pry.core.db.models_base import Base, _now

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
        String,
        Text,
    )

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

    # ── Audit log (security events — audit item #21) ──
    class AuditEvent(Base):
        __tablename__ = "audit_events"
        id = Column(Integer, primary_key=True)
        event_type = Column(String(64), index=True, nullable=False)
        actor = Column(String(128), default="", index=True)  # key_id / ip / "system"
        path = Column(String(256), default="", nullable=False)
        detail = Column(JSON, default=dict)
        created_at = Column(DateTime, default=_now, index=True, nullable=False)
        Index("ix_audit_events_type_created", event_type, created_at.desc())
