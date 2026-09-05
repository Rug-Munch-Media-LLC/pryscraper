"""Pry - SQLAlchemy models: scraping/monitoring domain.

Quality, intel, structure, monitors, accounts, browser sessions,
reports, pipelines, webhooks.

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
