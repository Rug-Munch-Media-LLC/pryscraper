"""Column definitions for the tables 0002's downgrade recreates EMPTY.

Loaded by path from the revision file (Alembic treats every .py in
``versions/`` as a revision, so this data module lives one level up).

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

import sqlalchemy as sa

_EMPTY_TABLES: dict[str, tuple[sa.Column, ...]] = {
    "review_items": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fields", sa.JSON(), server_default="{}"),
        sa.Column("status", sa.String(16), server_default="pending", index=True),
        sa.Column("reviewer", sa.String(128), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("submitted_at", sa.DateTime(), index=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    ),
    "costing_entries": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False, index=True),
        sa.Column("cost_usd", sa.Float(), server_default="0.0"),
        sa.Column("units", sa.Float(), server_default="1.0"),
        sa.Column("provider", sa.String(64), server_default=""),
        sa.Column("metadata", sa.JSON(), server_default="{}"),
        sa.Column("ts", sa.DateTime(), index=True),
    ),
    "freshness_snapshots": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, index=True),
        sa.Column("content_hash", sa.String(64), server_default=""),
        sa.Column("fingerprint", sa.String(128), server_default=""),
        sa.Column("checked_at", sa.DateTime(), index=True),
    ),
    "seo_snapshots": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, index=True),
        sa.Column("title", sa.Text(), server_default=""),
        sa.Column("meta_description", sa.Text(), server_default=""),
        sa.Column("h1", sa.Text(), server_default=""),
        sa.Column("keyword_count", sa.Integer(), server_default="0"),
        sa.Column("readability_score", sa.Float(), server_default="0.0"),
        sa.Column("full_data", sa.JSON(), server_default="{}"),
        sa.Column("checked_at", sa.DateTime(), index=True),
    ),
    "training_datasets": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("dataset_name", sa.String(256), server_default=""),
        sa.Column("license_class", sa.String(64), server_default="unknown"),
        sa.Column("pii_redacted", sa.Boolean(), server_default="0"),
        sa.Column("record_count", sa.Integer(), server_default="0"),
        sa.Column("file_path", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime()),
    ),
    "pipeline_runs": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.String(64), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.Column("status", sa.String(16), server_default="success"),
        sa.Column("result", sa.JSON(), server_default="{}"),
    ),
    "gdpr_requests": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("request_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(256), nullable=False, index=True),
        sa.Column("status", sa.String(16), server_default="pending"),
        sa.Column("requested_at", sa.DateTime(), index=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("details", sa.JSON(), server_default="{}"),
    ),
    "agency_clients": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("agency_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("email", sa.String(256), server_default=""),
        sa.Column("quota_used", sa.Integer(), server_default="0"),
        sa.Column("quota_limit", sa.Integer(), server_default="1000"),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime()),
    ),
    "actor_runs": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(), index=True),
        sa.Column("status", sa.String(16), server_default="success"),
        sa.Column("result", sa.JSON(), server_default="{}"),
        sa.Column("cost_usd", sa.Float(), server_default="0.0"),
    ),
    "llm_usage": (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False, index=True),
        sa.Column("model", sa.String(128), server_default=""),
        sa.Column("input_tokens", sa.Integer(), server_default="0"),
        sa.Column("output_tokens", sa.Integer(), server_default="0"),
        sa.Column("cost_usd", sa.Float(), server_default="0.0"),
        sa.Column("operation", sa.String(64), server_default=""),
        sa.Column("ts", sa.DateTime(), index=True),
    ),
    "x402_receipts": (
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
    ),
}

_FOREIGN_KEYS: dict[str, tuple[sa.ForeignKeyConstraint, ...]] = {
    "pipeline_runs": (sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.pipeline_id"]),),
    "agency_clients": (sa.ForeignKeyConstraint(["agency_id"], ["agencies.agency_id"]),),
    "actor_runs": (sa.ForeignKeyConstraint(["actor_id"], ["actors.actor_id"]),),
}


def create_tables(op: Any) -> None:
    """Recreate every dropped table EMPTY, with its primary key and FKs."""
    for name, columns in _EMPTY_TABLES.items():
        op.create_table(
            name,
            *columns,
            sa.PrimaryKeyConstraint("id"),
            *_FOREIGN_KEYS.get(name, ()),
        )
