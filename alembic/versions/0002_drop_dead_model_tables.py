"""drop dead model tables — remove 11 models with zero live consumers

Removes tables whose ORM models were deleted from db.py (2026-08-14).
Each model had no live (non-test) importers; the JSON stores remain
untouched (the SQL migration is one-way data-wise, downgrade recreates
the empty tables for reversibility but cannot restore rows).

Dropped models:
  - ReviewItem        (review_items)
  - CostingEntry      (costing_entries)
  - FreshnessSnapshot (freshness_snapshots)
  - SeoSnapshot       (seo_snapshots)
  - TrainingDataset   (training_datasets)
  - PipelineRun       (pipeline_runs)
  - GdprRequest       (gdpr_requests)
  - AgencyClient      (agency_clients)
  - ActorRun          (actor_runs)
  - LlmUsage          (llm_usage)
  - X402Receipt       (x402_receipts)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14 00:00:00.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop child tables before parents (none of the parents are dropped,
    # but keeping order consistent with 0001's downgrade anyway).
    op.drop_table("x402_receipts")
    op.drop_table("llm_usage")
    op.drop_table("actor_runs")
    op.drop_table("agency_clients")
    op.drop_table("gdpr_requests")
    op.drop_table("pipeline_runs")
    op.drop_table("training_datasets")
    op.drop_table("seo_snapshots")
    op.drop_table("freshness_snapshots")
    op.drop_table("costing_entries")
    op.drop_table("review_items")


def downgrade() -> None:
    # Recreate the tables (empty) so `alembic downgrade 0001` is reversible.
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
        sa.Column("facilitator", sa.String(64), server_default="x402.org"),
        sa.PrimaryKeyConstraint("id"),
    )
