"""Pry — Database layer using SQLAlchemy (SQLite/PostgreSQL).
Replaces JSON file storage for production safety."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Try to import SQLAlchemy
try:
    from sqlalchemy import (
        JSON,
        Boolean,
        Column,
        DateTime,
        Float,
        Integer,
        String,
        Text,
        create_engine,
    )
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.orm import Session, declarative_base, sessionmaker
    _has_sqlalchemy = True
    Base = declarative_base()
except ImportError:
    _has_sqlalchemy = False
    Base = None


if _has_sqlalchemy:
    class ApiKey(Base):
        __tablename__ = "api_keys"
        id = Column(Integer, primary_key=True, autoincrement=True)
        key_hash = Column(String(64), unique=True, nullable=False, index=True)
        user_id = Column(String(32), nullable=False, index=True)
        name = Column(String(100), default="default")
        rate_limit_rpm = Column(Integer, default=60)
        created_at = Column(DateTime, default=lambda: datetime.now(UTC))
        last_used = Column(DateTime, nullable=True)
        use_count = Column(Integer, default=0)
        active = Column(Boolean, default=True)

    class User(Base):
        __tablename__ = "users"
        id = Column(String(32), primary_key=True)
        email = Column(String(255), unique=True, nullable=False, index=True)
        password_hash = Column(String(128), nullable=False)
        salt = Column(String(64), nullable=False)
        role = Column(String(20), default="user")
        created_at = Column(DateTime, default=lambda: datetime.now(UTC))
        active = Column(Boolean, default=True)
        metadata_json = Column("metadata", JSON, default=dict)

    class UsageRecord(Base):
        __tablename__ = "usage_records"
        id = Column(Integer, primary_key=True, autoincrement=True)
        api_key_id = Column(Integer, index=True)
        operation = Column(String(50), nullable=False, index=True)
        quantity = Column(Float, default=1.0)
        cost_usd = Column(Float, default=0.0)
        timestamp = Column(DateTime, default=lambda: datetime.now(UTC), index=True)
        metadata_json = Column("metadata", JSON, default=dict)

    class QualityCheckRecord(Base):
        __tablename__ = "quality_checks"
        id = Column(Integer, primary_key=True, autoincrement=True)
        url_hash = Column(String(16), index=True)
        url = Column(String(2048), nullable=False)
        data = Column(JSON, default=dict)
        quality_score = Column(Float, default=0.0)
        anomaly_count = Column(Integer, default=0)
        checked_at = Column(DateTime, default=lambda: datetime.now(UTC))

    class ReviewRequest(Base):
        __tablename__ = "review_requests"
        id = Column(String(12), primary_key=True)
        user_id = Column(String(32), index=True)
        status = Column(String(20), default="pending", index=True)
        data = Column(JSON, default=dict)
        confidence_score = Column(Float, default=0.0)
        flagged_fields = Column(JSON, default=list)
        created_at = Column(DateTime, default=lambda: datetime.now(UTC))
        reviewed_at = Column(DateTime, nullable=True)
        reviewed_by = Column(String(100), nullable=True)
        review_notes = Column(Text, default="")

    class MonitorRecord(Base):
        __tablename__ = "monitors"
        id = Column(String(12), primary_key=True)
        user_id = Column(String(32), index=True)
        name = Column(String(200), nullable=False)
        target_url = Column(String(2048), nullable=False)
        schedule_cron = Column(String(50), default="0 */6 * * *")
        goal = Column(Text, default="")
        webhook_url = Column(String(2048), default="")
        status = Column(String(20), default="active")
        created_at = Column(DateTime, default=lambda: datetime.now(UTC))
        last_run_at = Column(DateTime, nullable=True)
        total_checks = Column(Integer, default=0)
        total_changes = Column(Integer, default=0)

    class AgencyClient(Base):
        __tablename__ = "agency_clients"
        id = Column(String(12), primary_key=True)
        agency_id = Column(String(32), index=True)
        name = Column(String(200), nullable=False)
        email = Column(String(255), nullable=False)
        api_key_hash = Column(String(64), unique=True)
        monthly_quota = Column(Integer, default=10000)
        usage_this_month = Column(Integer, default=0)
        status = Column(String(20), default="active")
        created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class Database:
    """SQLAlchemy database wrapper. Supports SQLite (default) and PostgreSQL."""

    def __init__(self, url: str = ""):
        if not _has_sqlalchemy:
            logger.warning("sqlalchemy_not_available")
            return
        if not url:
            url = os.getenv("PRY_DATABASE_URL", "sqlite:///~/.pry/data.db")
        # Ensure directory exists
        if url.startswith("sqlite:///"):
            db_path = url[10:]
            os.makedirs(os.path.dirname(os.path.expanduser(db_path)), exist_ok=True)
            url = f"sqlite:///{os.path.expanduser(db_path)}"
        self.engine = create_engine(url, echo=False, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)
        # Create tables
        Base.metadata.create_all(self.engine)
        logger.info("database_initialized", extra={"url": url.split("@")[-1]})

    @contextmanager
    def session(self) -> Generator[Any, None, None]:
        if not _has_sqlalchemy:
            yield None
            return
        s = self.Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def is_available(self) -> bool:
        return _has_sqlalchemy


_db: Database | None = None


def get_db() -> Database | None:
    """Get or create the global database instance."""
    global _db
    if _db is None and _has_sqlalchemy:
        _db = Database()
    return _db
