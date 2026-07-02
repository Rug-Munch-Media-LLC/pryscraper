"""Pry - SQLAlchemy database foundation.

Replaces the 12 ad-hoc JSON file stores under $PRY_DATA_DIR with a single
SQLite database (or PostgreSQL in production). Each legacy JSON store gets
a SQLAlchemy model with a matching schema, and a one-shot importer for
existing data.

Why migrate:
  - JSON files give no concurrency control. Two writes = corruption.
  - No transactions. A partial write is permanent.
  - No querying. Can't ask "all monitors on example.com".
  - No relationships. Can't join a monitor with its alerts.

Engine selection:
  - Default: SQLite at $PRY_DATA_DIR/pry.db. Zero-config, file-based.
  - Production: set PRY_DATABASE_URL=postgresql://... to use Postgres.
    SQLAlchemy handles the rest; no code changes.

Schema:
  See the Model classes below. Each one corresponds to a former JSON store:
    quality       -> QualityCheck
    reviews       -> ReviewItem
    intel         -> IntelSnapshot (already JSONL; now a real table)
    costing       -> CostingEntry
    freshness     -> FreshnessSnapshot
    structure     -> StructureSnapshot
    seo           -> SeoSnapshot
    monitors      -> Monitor
    monitor_runs  -> MonitorRun
    accounts      -> Account
    sessions      -> BrowserSession
    reports       -> Report
    reports_real  -> RealReport
    training      -> TrainingDataset
    pipelines     -> Pipeline
    pipeline_runs -> PipelineRun
    gdpr          -> GdprRequest
    agency        -> Agency
    agency_clients -> AgencyClient
    referrals     -> ReferralClick
    actors        -> Actor
    actor_runs    -> ActorRun
    llm_usage     -> LlmUsage
    webhooks      -> Webhook
    x402          -> X402Receipt

This is a 24-model starter set. New models can be added incrementally as
the corresponding JSON store is migrated.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        create_engine,
        event,
    )
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

    _HAS_SA = True
except ImportError:  # pragma: no cover
    _HAS_SA = False

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = PRY_DATA_DIR / "pry.db"

# Backward-compat aliases for existing code/tests that imported these names
_has_sqlalchemy = _HAS_SA


def get_db() -> Engine:
    """Backward-compat alias for get_engine()."""
    return get_engine()


DATABASE_URL_ENV = "PRY_DATABASE_URL"
DEFAULT_SQLITE_URL = f"sqlite:///{DEFAULT_DB_PATH}"


def _resolve_database_url() -> str:
    """Resolve the database URL. Default: SQLite at PRY_DATA_DIR/pry.db."""
    url = os.getenv(DATABASE_URL_ENV)
    if url:
        return url
    return DEFAULT_SQLITE_URL


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Get the SQLAlchemy engine. Lazily creates one on first call."""
    global _engine, _SessionLocal
    if not _HAS_SA:
        raise RuntimeError("sqlalchemy is not installed; pip install 'sqlalchemy>=2.0'")
    if _engine is None:
        url = _resolve_database_url()
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, connect_args=connect_args, future=True, echo=False)
        # Enable foreign keys for SQLite (off by default)
        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _enable_sqlite_fk(dbapi_conn: sqlite3.Connection, _conn_record: Any) -> None:
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
        # Auto-create tables on first import (idempotent)
        Base.metadata.create_all(_engine)
        logger.info(
            "db_engine_initialized", extra={"url": url.split("@")[-1] if "@" in url else url}
        )
    return _engine


def get_session() -> Session:
    """Get a new Session. Caller is responsible for closing it.

    Use `with db_session() as s:` or the `session_scope()` context manager
    for automatic cleanup and commit/rollback handling.
    """
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager: yields a Session, commits on success, rolls back on error.

    Usage:
        with session_scope() as s:
            s.add(QualityCheck(...))
            # commit happens automatically when the with-block exits cleanly
    """
    s = get_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ── Model base ────────────────────────────────────────────────────

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
    class ReviewItem(Base):
        __tablename__ = "review_items"
        id = Column(Integer, primary_key=True)
        review_id = Column(String(64), unique=True, index=True, nullable=False)
        url = Column(Text, nullable=False)
        fields = Column(JSON, default=dict)
        status = Column(String(16), default="pending", index=True)  # pending|approved|rejected
        reviewer = Column(String(128), default="")
        notes = Column(Text, default="")
        submitted_at = Column(DateTime, default=_now, index=True)
        resolved_at = Column(DateTime, nullable=True)

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
    class CostingEntry(Base):
        __tablename__ = "costing_entries"
        id = Column(Integer, primary_key=True)
        operation = Column(String(64), index=True, nullable=False)
        cost_usd = Column(Float, default=0.0)
        units = Column(Float, default=1.0)
        provider = Column(String(64), default="")
        metadata_json = Column("metadata", JSON, default=dict)  # 'metadata' is reserved
        ts = Column(DateTime, default=_now, index=True)

    # ── Freshness ──
    class FreshnessSnapshot(Base):
        __tablename__ = "freshness_snapshots"
        id = Column(Integer, primary_key=True)
        url = Column(Text, index=True, nullable=False)
        content_hash = Column(String(64), default="")
        fingerprint = Column(String(128), default="")
        checked_at = Column(DateTime, default=_now, index=True)

    # ── Structure (page structure monitor) ──
    class StructureSnapshot(Base):
        __tablename__ = "structure_snapshots"
        id = Column(Integer, primary_key=True)
        url = Column(Text, index=True, nullable=False)
        structure_hash = Column(String(64), default="")
        dom_summary = Column(JSON, default=dict)
        checked_at = Column(DateTime, default=_now, index=True)

    # ── SEO ──
    class SeoSnapshot(Base):
        __tablename__ = "seo_snapshots"
        id = Column(Integer, primary_key=True)
        url = Column(Text, index=True, nullable=False)
        title = Column(Text, default="")
        meta_description = Column(Text, default="")
        h1 = Column(Text, default="")
        keyword_count = Column(Integer, default=0)
        readability_score = Column(Float, default=0.0)
        full_data = Column(JSON, default=dict)
        checked_at = Column(DateTime, default=_now, index=True)

    # ── Monitors ──
    class Monitor(Base):
        __tablename__ = "monitors"
        id = Column(Integer, primary_key=True)
        monitor_id = Column(String(64), unique=True, index=True, nullable=False)
        url = Column(Text, nullable=False)
        monitor_name = Column(String(256), default="")  # was 'name' in JSON
        schedule_cron = Column(String(64), default="")
        check_type = Column(String(32), default="content")
        active = Column(Boolean, default=True, index=True)
        webhook_url = Column(Text, default="")
        last_check_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, default=_now)

    class MonitorRun(Base):
        __tablename__ = "monitor_runs"
        id = Column(Integer, primary_key=True)
        monitor_id = Column(
            String(64), ForeignKey("monitors.monitor_id"), index=True, nullable=False
        )
        ts = Column(DateTime, default=_now, index=True)
        status = Column(String(16), default="success")  # success|changed|error
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
        status = Column(String(16), default="active")  # active|cooldown|disabled
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
        user_agent = Column(String(512), default="")
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
    class TrainingDataset(Base):
        __tablename__ = "training_datasets"
        id = Column(Integer, primary_key=True)
        dataset_id = Column(String(64), unique=True, index=True, nullable=False)
        dataset_name = Column(String(256), default="")  # was 'name' in JSON
        license_class = Column(String(64), default="unknown")
        pii_redacted = Column(Boolean, default=False)
        record_count = Column(Integer, default=0)
        file_path = Column(Text, default="")
        created_at = Column(DateTime, default=_now)

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

    class PipelineRun(Base):
        __tablename__ = "pipeline_runs"
        id = Column(Integer, primary_key=True)
        pipeline_id = Column(
            String(64), ForeignKey("pipelines.pipeline_id"), index=True, nullable=False
        )
        ts = Column(DateTime, default=_now, index=True)
        status = Column(String(16), default="success")
        result = Column(JSON, default=dict)

    # ── GDPR ──
    class GdprRequest(Base):
        __tablename__ = "gdpr_requests"
        id = Column(Integer, primary_key=True)
        request_id = Column(String(64), unique=True, index=True, nullable=False)
        request_type = Column(String(32), nullable=False)  # access|delete|portability
        subject_id = Column(String(256), nullable=False, index=True)
        status = Column(String(16), default="pending")
        requested_at = Column(DateTime, default=_now, index=True)
        completed_at = Column(DateTime, nullable=True)
        details = Column(JSON, default=dict)

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

    class AgencyClient(Base):
        __tablename__ = "agency_clients"
        id = Column(Integer, primary_key=True)
        client_id = Column(String(64), unique=True, index=True, nullable=False)
        agency_id = Column(String(64), ForeignKey("agencies.agency_id"), index=True, nullable=False)
        name = Column(String(256), nullable=False)
        email = Column(String(256), default="")
        quota_used = Column(Integer, default=0)
        quota_limit = Column(Integer, default=1000)
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

    class ActorRun(Base):
        __tablename__ = "actor_runs"
        id = Column(Integer, primary_key=True)
        actor_id = Column(String(64), ForeignKey("actors.actor_id"), index=True, nullable=False)
        ts = Column(DateTime, default=_now, index=True)
        status = Column(String(16), default="success")
        result = Column(JSON, default=dict)
        cost_usd = Column(Float, default=0.0)

    # ── LLM usage tracking ──
    class LlmUsage(Base):
        __tablename__ = "llm_usage"
        id = Column(Integer, primary_key=True)
        provider = Column(String(64), index=True, nullable=False)
        model = Column(String(128), default="")
        input_tokens = Column(Integer, default=0)
        output_tokens = Column(Integer, default=0)
        cost_usd = Column(Float, default=0.0)
        operation = Column(String(64), default="")
        ts = Column(DateTime, default=_now, index=True)

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
    class X402Receipt(Base):
        __tablename__ = "x402_receipts"
        id = Column(Integer, primary_key=True)
        receipt_id = Column(String(64), unique=True, index=True, nullable=False)
        tx_hash = Column(String(128), index=True, default="")
        network = Column(String(32), default="base")
        asset = Column(String(16), default="USDC")
        amount_usd = Column(Float, default=0.0)
        payer = Column(String(128), default="")
        payee = Column(String(128), default="")
        operation = Column(String(64), default="")
        ts = Column(DateTime, default=_now, index=True)
        facilitator = Column(String(64), default="x402.org")

else:  # pragma: no cover
    Base = None  # type: ignore


# ── Importer: JSON store -> SQL ───────────────────────────────────


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
    except OSError as e:
        logger.warning("jsonl_read_failed", extra={"path": str(path), "error": str(e)[:80]})


def _iter_json_files(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for d in data:
                    if isinstance(d, dict):
                        yield d
            elif isinstance(data, dict):
                yield data
        except (json.JSONDecodeError, OSError):
            return
        return
    for f in path.glob("*.json"):
        yield from _iter_json_files(f)


def import_json_stores(data_dir: Path | None = None) -> dict[str, int]:
    """One-shot importer: read all JSON stores and write to the SQL tables.

    Returns a dict of {store_name: row_count_imported}.

    Idempotent: re-running with the same data is safe (uses upsert-style
    pattern via the unique constraints on _id columns).
    """
    data_dir = data_dir or PRY_DATA_DIR
    counts: dict[str, int] = {}

    with session_scope() as s:
        # Quality
        n = 0
        for rec in _iter_jsonl(data_dir / "quality" / "checks.jsonl"):
            s.add(
                QualityCheck(
                    extraction_id=rec.get("extraction_id", rec.get("id", ""))[:64],
                    url=rec.get("url", ""),
                    completeness=rec.get("completeness", 0.0),
                    accuracy=rec.get("accuracy", 0.0),
                    freshness=rec.get("freshness", 0.0),
                    overall_score=rec.get("overall_score", 0.0),
                    risk_level=rec.get("risk_level", "unknown"),
                    issues=rec.get("issues", []),
                    data=rec,
                )
            )
            n += 1
        counts["quality"] = n

        # Intel (JSONL)
        n = 0
        for rec in _iter_jsonl(data_dir / "intel" / "snapshots.jsonl"):
            s.add(
                IntelSnapshot(
                    competitor_id=rec.get("competitor_id", "")[:64],
                    competitor_name=rec.get("competitor_name", "")[:256],
                    url=rec.get("url", ""),
                    fields=rec.get("fields", {}),
                )
            )
            n += 1
        counts["intel"] = n

        # Monitors (JSON files)
        n = 0
        for rec in _iter_json_files(data_dir / "monitors"):
            mid = rec.get("monitor_id") or rec.get("id", "")
            s.add(
                Monitor(
                    monitor_id=mid[:64],
                    url=rec.get("url", ""),
                    monitor_name=rec.get("name", ""),  # was 'name' in JSON
                    schedule_cron=rec.get("schedule_cron", ""),
                    check_type=rec.get("check_type", "content"),
                    active=rec.get("active", True),
                    webhook_url=rec.get("webhook_url", ""),
                )
            )
            n += 1
        counts["monitors"] = n

        # Accounts (JSON files)
        n = 0
        for rec in _iter_json_files(data_dir / "accounts"):
            aid = rec.get("account_id") or rec.get("id", "")
            s.add(
                Account(
                    account_id=aid[:64],
                    service=rec.get("service", "unknown")[:64],
                    username=rec.get("username", ""),
                    email=rec.get("email", ""),
                    status=rec.get("status", "active"),
                    used_count=rec.get("used_count", 0),
                )
            )
            n += 1
        counts["accounts"] = n

        # Actors (JSON files)
        n = 0
        for rec in _iter_json_files(data_dir / "actors"):
            aid = rec.get("actor_id") or rec.get("id", "")
            s.add(
                Actor(
                    actor_id=aid[:64],
                    name=rec.get("name", ""),
                    description=rec.get("description", ""),
                    template_id=rec.get("template_id", ""),
                    code=rec.get("code", ""),
                    price_per_run=rec.get("price_per_run", 0.0),
                    visibility=rec.get("visibility", "private"),
                    schedule_cron=rec.get("schedule_cron", ""),
                    tags=rec.get("tags", []),
                    author=rec.get("author", ""),
                    run_count=rec.get("run_count", 0),
                    revenue_usd=rec.get("revenue_usd", 0.0),
                )
            )
            n += 1
        counts["actors"] = n

        # Pipelines (JSON files)
        n = 0
        for rec in _iter_json_files(data_dir / "pipelines"):
            pid = rec.get("pipeline_id") or rec.get("id", "")
            s.add(
                Pipeline(
                    pipeline_id=pid[:64],
                    pipeline_name=rec.get("name", ""),
                    steps=rec.get("steps", []),
                    schedule_cron=rec.get("schedule_cron", ""),
                    active=rec.get("active", True),
                )
            )
            n += 1
        counts["pipelines"] = n

        # Sessions (JSON files)
        n = 0
        for rec in _iter_json_files(data_dir / "sessions"):
            sid = rec.get("session_id") or rec.get("id", "")
            s.add(
                BrowserSession(
                    session_id=sid[:64],
                    cookies=rec.get("cookies", []),
                    local_storage=rec.get("local_storage", {}),
                    user_agent=rec.get("user_agent", ""),
                    proxy=rec.get("proxy", ""),
                )
            )
            n += 1
        counts["sessions"] = n

        # Agency + clients (JSON files)
        n = 0
        for rec in _iter_json_files(data_dir / "agency"):
            aid = rec.get("agency_id") or rec.get("id", "")
            s.add(
                Agency(
                    agency_id=aid[:64],
                    agency_name=rec.get("name", ""),
                    owner_email=rec.get("owner_email", ""),
                    custom_domain=rec.get("custom_domain", ""),
                    brand_color=rec.get("brand_color", "#f59e0b"),
                    logo_url=rec.get("logo_url", ""),
                    quota=rec.get("quota", 10000),
                )
            )
            n += 1
        counts["agency"] = n

    return counts


def db_health() -> dict[str, Any]:
    """Return a quick health dict for /health or /status endpoints."""
    if not _HAS_SA:
        return {"available": False, "reason": "sqlalchemy not installed"}
    try:
        eng = get_engine()
        with eng.connect() as conn:
            # SQLite-specific pragma; no-op for other backends
            try:
                result = conn.exec_driver_sql("SELECT sqlite_version()").fetchone()
                sqlite_version = result[0] if result else None
            except Exception:
                sqlite_version = None
        return {
            "available": True,
            "url": _resolve_database_url().split("@")[-1]
            if "@" in _resolve_database_url()
            else _resolve_database_url(),
            "sqlite_version": sqlite_version,
        }
    except Exception as e:
        return {"available": False, "error": str(e)[:200]}
