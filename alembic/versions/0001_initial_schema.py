"""initial schema — create all 26 model tables

Revision ID: 0001
Revises:
Create Date: 2026-07-03 00:00:00.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quality_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("extraction_id", sa.String(64), nullable=False, index=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("completeness", sa.Float(), server_default="0.0"),
        sa.Column("accuracy", sa.Float(), server_default="0.0"),
        sa.Column("freshness", sa.Float(), server_default="0.0"),
        sa.Column("overall_score", sa.Float(), server_default="0.0"),
        sa.Column("risk_level", sa.String(16), server_default="unknown"),
        sa.Column("issues", sa.JSON(), server_default="[]"),
        sa.Column("checked_at", sa.DateTime(), index=True),
        sa.Column("data", sa.JSON(), server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "review_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fields", sa.JSON(), server_default="{}"),
        sa.Column("status", sa.String(16), server_default="pending", index=True),
        sa.Column("reviewer", sa.String(128), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("submitted_at", sa.DateTime(), index=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "intel_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.String(64), nullable=False, index=True),
        sa.Column("competitor_name", sa.String(256), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fields", sa.JSON(), server_default="{}"),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_intel_competitor_ts", "intel_snapshots", ["competitor_id", sa.text("ts DESC")]
    )
    op.create_table(
        "costing_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False, index=True),
        sa.Column("cost_usd", sa.Float(), server_default="0.0"),
        sa.Column("units", sa.Float(), server_default="1.0"),
        sa.Column("provider", sa.String(64), server_default=""),
        sa.Column("metadata", sa.JSON(), server_default="{}"),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "freshness_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, index=True),
        sa.Column("content_hash", sa.String(64), server_default=""),
        sa.Column("fingerprint", sa.String(128), server_default=""),
        sa.Column("checked_at", sa.DateTime(), index=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "structure_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, index=True),
        sa.Column("url_hash", sa.String(64), server_default="", index=True),
        sa.Column("template_id", sa.String(128), server_default="", index=True),
        sa.Column("structure_hash", sa.String(64), server_default=""),
        sa.Column("selectors", sa.JSON(), server_default="[]"),
        sa.Column("all_matched", sa.Boolean(), server_default="0"),
        sa.Column("matched_count", sa.Integer(), server_default="0"),
        sa.Column("failed_count", sa.Integer(), server_default="0"),
        sa.Column("changes", sa.JSON(), server_default="[]"),
        sa.Column("change_count", sa.Integer(), server_default="0"),
        sa.Column("has_changes", sa.Boolean(), server_default="0"),
        sa.Column("dom_summary", sa.JSON(), server_default="{}"),
        sa.Column("checked_at", sa.DateTime(), index=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "seo_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, index=True),
        sa.Column("title", sa.Text(), server_default=""),
        sa.Column("meta_description", sa.Text(), server_default=""),
        sa.Column("h1", sa.Text(), server_default=""),
        sa.Column("keyword_count", sa.Integer(), server_default="0"),
        sa.Column("readability_score", sa.Float(), server_default="0.0"),
        sa.Column("full_data", sa.JSON(), server_default="{}"),
        sa.Column("checked_at", sa.DateTime(), index=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "monitors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitor_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("monitor_name", sa.String(256), server_default=""),
        sa.Column("schedule_cron", sa.String(64), server_default=""),
        sa.Column("check_type", sa.String(32), server_default="content"),
        sa.Column("goal", sa.Text(), server_default=""),
        sa.Column("use_llm_judge", sa.Boolean(), server_default="0"),
        sa.Column("active", sa.Boolean(), server_default="1", index=True),
        sa.Column("webhook_url", sa.Text(), server_default=""),
        sa.Column("last_check_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("current_version", sa.Integer(), server_default="0"),
        sa.Column("last_content", sa.Text(), server_default=""),
        sa.Column("total_checks", sa.Integer(), server_default="0"),
        sa.Column("total_changes", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "monitor_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitor_id", sa.String(64), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.Column("status", sa.String(16), server_default="success"),
        sa.Column("diff", sa.JSON(), server_default="{}"),
        sa.Column("error", sa.Text(), server_default=""),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.monitor_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("service", sa.String(64), nullable=False, index=True),
        sa.Column("username", sa.String(256), nullable=False),
        sa.Column("email", sa.String(256), server_default=""),
        sa.Column("status", sa.String(16), server_default="active"),
        sa.Column("used_count", sa.Integer(), server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("cookies", sa.JSON(), server_default="[]"),
        sa.Column("local_storage", sa.JSON(), server_default="{}"),
        sa.Column("user_agent", sa.String(512), server_default=""),
        sa.Column("proxy", sa.String(256), server_default=""),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("report_name", sa.String(256), server_default=""),
        sa.Column("report_type", sa.String(64), server_default="html"),
        sa.Column("url", sa.Text(), server_default=""),
        sa.Column("data", sa.JSON(), server_default="{}"),
        sa.Column("generated_at", sa.DateTime(), index=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "training_datasets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("dataset_name", sa.String(256), server_default=""),
        sa.Column("license_class", sa.String(64), server_default="unknown"),
        sa.Column("pii_redacted", sa.Boolean(), server_default="0"),
        sa.Column("record_count", sa.Integer(), server_default="0"),
        sa.Column("file_path", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("pipeline_name", sa.String(256), server_default=""),
        sa.Column("steps", sa.JSON(), server_default="[]"),
        sa.Column("schedule_cron", sa.String(64), server_default=""),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.String(64), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.Column("status", sa.String(16), server_default="success"),
        sa.Column("result", sa.JSON(), server_default="{}"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.pipeline_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "gdpr_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("request_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(256), nullable=False, index=True),
        sa.Column("status", sa.String(16), server_default="pending"),
        sa.Column("requested_at", sa.DateTime(), index=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("details", sa.JSON(), server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "agencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("agency_name", sa.String(256), nullable=False),
        sa.Column("owner_email", sa.String(256), nullable=False),
        sa.Column("custom_domain", sa.String(256), server_default=""),
        sa.Column("brand_color", sa.String(16), server_default="#f59e0b"),
        sa.Column("logo_url", sa.Text(), server_default=""),
        sa.Column("quota", sa.Integer(), server_default="10000"),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "agency_clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("agency_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("email", sa.String(256), server_default=""),
        sa.Column("quota_used", sa.Integer(), server_default="0"),
        sa.Column("quota_limit", sa.Integer(), server_default="1000"),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.agency_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "referral_clicks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("click_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("provider", sa.String(64), nullable=False, index=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source", sa.String(64), server_default=""),
        sa.Column("user_id", sa.String(128), server_default=""),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.Column("converted", sa.Boolean(), server_default="0"),
        sa.Column("conversion_value_usd", sa.Float(), server_default="0.0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "referral_conversions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("click_id", sa.String(64), nullable=False, index=True),
        sa.Column("provider", sa.String(64), nullable=False, index=True),
        sa.Column("revenue_usd", sa.Float(), server_default="0.0"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.ForeignKeyConstraint(["click_id"], ["referral_clicks.click_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "referral_in_app_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False, index=True),
        sa.Column("revenue_usd", sa.Float(), server_default="0.0"),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "actors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("template_id", sa.String(64), server_default=""),
        sa.Column("code", sa.Text(), server_default=""),
        sa.Column("price_per_run", sa.Float(), server_default="0.0"),
        sa.Column("visibility", sa.String(16), server_default="private"),
        sa.Column("schedule_cron", sa.String(64), server_default=""),
        sa.Column("tags", sa.JSON(), server_default="[]"),
        sa.Column("author", sa.String(128), server_default=""),
        sa.Column("run_count", sa.Integer(), server_default="0"),
        sa.Column("revenue_usd", sa.Float(), server_default="0.0"),
        sa.Column("created_at", sa.DateTime()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "actor_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.Column("status", sa.String(16), server_default="success"),
        sa.Column("result", sa.JSON(), server_default="{}"),
        sa.Column("cost_usd", sa.Float(), server_default="0.0"),
        sa.ForeignKeyConstraint(["actor_id"], ["actors.actor_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False, index=True),
        sa.Column("model", sa.String(128), server_default=""),
        sa.Column("input_tokens", sa.Integer(), server_default="0"),
        sa.Column("output_tokens", sa.Integer(), server_default="0"),
        sa.Column("cost_usd", sa.Float(), server_default="0.0"),
        sa.Column("operation", sa.String(64), server_default=""),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("webhook_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("events", sa.JSON(), server_default="[]"),
        sa.Column("secret", sa.String(128), server_default=""),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "x402_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("tx_hash", sa.String(128), index=True, server_default=""),
        sa.Column("network", sa.String(32), server_default="base"),
        sa.Column("asset", sa.String(16), server_default="USDC"),
        sa.Column("amount_usd", sa.Float(), server_default="0.0"),
        sa.Column("payer", sa.String(128), server_default=""),
        sa.Column("payee", sa.String(128), server_default=""),
        sa.Column("operation", sa.String(64), server_default=""),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.Column("facilitator", sa.String(64), server_default="pry.payments.x402.org"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("x402_receipts")
    op.drop_table("webhooks")
    op.drop_table("llm_usage")
    op.drop_table("actor_runs")
    op.drop_table("actors")
    op.drop_table("referral_in_app_usage")
    op.drop_table("referral_conversions")
    op.drop_table("referral_clicks")
    op.drop_table("agency_clients")
    op.drop_table("agencies")
    op.drop_table("gdpr_requests")
    op.drop_table("pipeline_runs")
    op.drop_table("pipelines")
    op.drop_table("training_datasets")
    op.drop_table("reports")
    op.drop_table("browser_sessions")
    op.drop_table("accounts")
    op.drop_table("monitor_runs")
    op.drop_table("monitors")
    op.drop_table("seo_snapshots")
    op.drop_table("structure_snapshots")
    op.drop_table("freshness_snapshots")
    op.drop_table("costing_entries")
    op.drop_table("intel_snapshots")
    op.drop_table("review_items")
    op.drop_table("quality_checks")
