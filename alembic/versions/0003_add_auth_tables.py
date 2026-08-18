"""add auth tables — User, APIKey, Usage, ScrapeJob

Adds authentication and usage tracking tables for production deployment.

Tables:
  - users: User accounts with tier/role, password hashing
  - api_keys: API keys with scopes, rate limits, quotas
  - usage: Per-request usage tracking for billing/analytics
  - scrape_jobs: Async job tracking for long-running operations

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-18 00:00:00.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("email", sa.String(256), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("tier", sa.String(32), server_default="FREE", nullable=False),
        sa.Column("role", sa.String(32), server_default="USER", nullable=False),
        sa.Column("wallet", sa.String(128), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False, index=True),
        sa.Column("is_verified", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # NOTE: user_id and email have unique=True, index=True in model → auto-indexed
    # No explicit op.create_index() needed for them

    # ── api_keys ───────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True, index=True),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(128), server_default="", nullable=False),
        sa.Column("scopes", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("rate_limit_rpm", sa.Integer(), server_default="120", nullable=False),
        sa.Column("quota_monthly", sa.Integer(), server_default="10000", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # NOTE: key_id, key_hash, user_id have index=True in model → auto-indexed
    # No explicit op.create_index() needed

    # ── usage ──────────────────────────────────────────────────────────────
    op.create_table(
        "usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("api_key_id", sa.String(64), nullable=True, index=True),
        sa.Column("operation", sa.String(64), nullable=False, index=True),
        sa.Column("endpoint", sa.String(128), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="success", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bytes_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bytes_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("ip", sa.String(64), server_default="", nullable=False),
        sa.Column("user_agent", sa.String(512), server_default="", nullable=False),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            index=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.key_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_user_created", "usage", ["user_id", "created_at"])
    op.create_index("ix_usage_operation_created", "usage", ["operation", "created_at"])

    # ── scrape_jobs ────────────────────────────────────────────────────────
    op.create_table(
        "scrape_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("api_key_id", sa.String(64), nullable=True, index=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("input_data", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("result_data", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("progress", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("total_urls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_urls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_urls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.key_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # NOTE: job_id has unique=True, index=True in model → auto-indexed
    op.create_index("ix_scrape_jobs_user_status", "scrape_jobs", ["user_id", "status"])
    op.create_index("ix_scrape_jobs_created", "scrape_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_scrape_jobs_created", table_name="scrape_jobs")
    op.drop_index("ix_scrape_jobs_user_status", table_name="scrape_jobs")
    # NOTE: job_id index is auto-created by unique=True, index=True in model
    op.drop_table("scrape_jobs")

    op.drop_index("ix_usage_operation_created", table_name="usage")
    op.drop_index("ix_usage_user_created", table_name="usage")
    op.drop_table("usage")

    # NOTE: key_id, key_hash, user_id indexes are auto-created by index=True in model
    op.drop_table("api_keys")

    # NOTE: user_id and email indexes are auto-created by unique=True, index=True in model
    op.drop_table("users")
