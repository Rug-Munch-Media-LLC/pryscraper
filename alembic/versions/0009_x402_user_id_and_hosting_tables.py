"""x402 customer attribution, ledger uniqueness, hosting tables, usage.payment_id

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17 00:00:00.000000

Fixes four verified drift defects between the models and the schema:

1. ``x402_payment_records`` / ``x402_settlement_records`` had no ``user_id``,
   while ``payments/x402/ledger_store.py`` writes it on every insert.
2. ``hosting_plans`` / ``hosted_instances`` exist as models with no migration.
3. ``x402_payment_records`` had no UNIQUE(payment_id, tx_hash), so a retried
   insert produced duplicate ledger rows instead of hitting the idempotent
   path.
4. ``usage`` had no ``payment_id``, blocking credits-vs-calls reconciliation.

SQLite safety: plain ``op.add_column`` (additive only), unique enforcement via
``create_index(unique=True)`` rather than ADD CONSTRAINT, no CONCURRENTLY.
NULL ``tx_hash`` values are backfilled to ``''`` before the unique index is
created, because NULLs are distinct in a UNIQUE index on both SQLite and
Postgres and would let duplicates through.

Every step is existence-guarded. ``get_engine()`` runs
``Base.metadata.create_all`` unless ``PRY_ALEMBIC_AUTO=0``, so on any DB the
app touched first the two hosting tables (new models) already exist; a blind
``create_table`` would abort the upgrade with "table already exists".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAYMENT = "x402_payment_records"
SETTLEMENT = "x402_settlement_records"
USAGE = "usage"
PLANS = "hosting_plans"
INSTANCES = "hosted_instances"

IX_PAYMENT_USER = "ix_x402_payment_records_user_id"
IX_SETTLEMENT_USER = "ix_x402_settlement_records_user_id"
UX_PAYMENT_TX = "ux_x402_payment_records_payment_tx"
IX_USAGE_PAYMENT = "ix_usage_payment_id"
IX_INSTANCE_USER_CREATED = "ix_hosted_instances_user_created"


def _inspect() -> sa.Inspector:
    """Fresh inspector per call — cached reflection goes stale after DDL."""
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspect().get_table_names()


def _has_column(table: str, column: str) -> bool:
    return any(col["name"] == column for col in _inspect().get_columns(table))


def _has_index(table: str, index: str) -> bool:
    return any(idx["name"] == index for idx in _inspect().get_indexes(table))


def _add_column_once(table: str, column: str, type_: sa.types.TypeEngine[Any]) -> None:
    if _has_column(table, column):
        return
    op.add_column(table, sa.Column(column, type_, server_default="", nullable=True))


def _create_index_once(table: str, index: str, columns: list[str], *, unique: bool = False) -> None:
    if _has_index(table, index):
        return
    op.create_index(index, table, columns, unique=unique)


def upgrade() -> None:
    # ── 1. customer attribution on both x402 ledger tables ──
    _add_column_once(PAYMENT, "user_id", sa.String(128))
    _create_index_once(PAYMENT, IX_PAYMENT_USER, ["user_id"])
    _add_column_once(SETTLEMENT, "user_id", sa.String(128))
    _create_index_once(SETTLEMENT, IX_SETTLEMENT_USER, ["user_id"])

    # ── 2. NULL tx_hash defeats UNIQUE: normalise, dedupe, then index ──
    if not _has_index(PAYMENT, UX_PAYMENT_TX):
        op.execute(sa.text("UPDATE x402_payment_records SET tx_hash = '' WHERE tx_hash IS NULL"))
        op.execute(
            sa.text(
                "DELETE FROM x402_payment_records WHERE id NOT IN ("
                "SELECT MIN(id) FROM x402_payment_records GROUP BY payment_id, tx_hash)"
            )
        )
        op.create_index(UX_PAYMENT_TX, PAYMENT, ["payment_id", "tx_hash"], unique=True)

    # ── 3. cloud hosting tables (models existed, schema did not) ──
    if not _has_table(PLANS):
        op.create_table(
            PLANS,
            sa.Column("tier", sa.String(32), nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("price_usd_monthly", sa.Float(), nullable=True),
            sa.Column("max_concurrent_scrapes", sa.Integer(), server_default="1", nullable=False),
            sa.Column("max_pages_month", sa.Integer(), nullable=True),
            sa.Column("storage_gb", sa.Integer(), server_default="1", nullable=False),
            sa.Column("features", sa.JSON(), server_default="[]", nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("tier"),
        )

    if not _has_table(INSTANCES):
        op.create_table(
            INSTANCES,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("instance_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("plan_tier", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), server_default="active", nullable=False),
            sa.Column("api_key", sa.String(64), server_default="", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("region", sa.String(32), server_default="us-east", nullable=False),
            sa.Column("resource_limit", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.user_id"],
                name="fk_hosted_instances_user_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_hosted_instances_instance_id", INSTANCES, ["instance_id"], unique=True)
        op.create_index("ix_hosted_instances_user_id", INSTANCES, ["user_id"])
        op.create_index("ix_hosted_instances_status", INSTANCES, ["status"])
        op.create_index("ix_hosted_instances_expires_at", INSTANCES, ["expires_at"])
        op.create_index(IX_INSTANCE_USER_CREATED, INSTANCES, ["user_id", "created_at"])

    # ── 4. reconciliation key on usage ──
    if not _has_column(USAGE, "payment_id"):
        op.add_column(USAGE, sa.Column("payment_id", sa.String(128), nullable=True))
    _create_index_once(USAGE, IX_USAGE_PAYMENT, ["payment_id"])


def downgrade() -> None:
    # The dedupe/backfill is intentionally not reversible: the deleted
    # duplicate ledger rows are the defect, not data to restore.
    if _has_index(USAGE, IX_USAGE_PAYMENT):
        op.drop_index(IX_USAGE_PAYMENT, table_name=USAGE)
    if _has_column(USAGE, "payment_id"):
        op.drop_column(USAGE, "payment_id")

    if _has_table(INSTANCES):
        op.drop_table(INSTANCES)
    if _has_table(PLANS):
        op.drop_table(PLANS)

    if _has_index(PAYMENT, UX_PAYMENT_TX):
        op.drop_index(UX_PAYMENT_TX, table_name=PAYMENT)
    if _has_index(SETTLEMENT, IX_SETTLEMENT_USER):
        op.drop_index(IX_SETTLEMENT_USER, table_name=SETTLEMENT)
    if _has_column(SETTLEMENT, "user_id"):
        op.drop_column(SETTLEMENT, "user_id")
    if _has_index(PAYMENT, IX_PAYMENT_USER):
        op.drop_index(IX_PAYMENT_USER, table_name=PAYMENT)
    if _has_column(PAYMENT, "user_id"):
        op.drop_column(PAYMENT, "user_id")
