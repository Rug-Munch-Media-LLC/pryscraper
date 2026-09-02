"""add x402 ledger tables — payment + settlement records (audit item #2)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-02 00:00:00.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "x402_payment_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.String(128), nullable=False),
        sa.Column("tx_hash", sa.String(80), server_default=""),
        sa.Column("network", sa.String(64), server_default=""),
        sa.Column("asset", sa.String(32), server_default=""),
        sa.Column("amount_usd", sa.Float(), server_default="0"),
        sa.Column("required_amount_atomic", sa.String(64), server_default=""),
        sa.Column("operation", sa.String(64), server_default=""),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("facilitator", sa.String(64), server_default=""),
        sa.Column("caller_key", sa.String(128), server_default=""),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("record", sa.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_x402_payment_records_payment_id", "x402_payment_records", ["payment_id"])
    op.create_index("ix_x402_payment_records_tx_hash", "x402_payment_records", ["tx_hash"])
    op.create_index("ix_x402_payment_records_operation", "x402_payment_records", ["operation"])
    op.create_index("ix_x402_payment_records_verified", "x402_payment_records", ["verified"])
    op.create_index("ix_x402_payment_records_expires_at", "x402_payment_records", ["expires_at"])
    op.create_index("ix_x402_payment_records_created_at", "x402_payment_records", ["created_at"])

    op.create_table(
        "x402_settlement_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("settlement_key", sa.String(256), nullable=False),
        sa.Column("payment_id", sa.String(128), nullable=False),
        sa.Column("tx_hash", sa.String(80), server_default=""),
        sa.Column("network", sa.String(64), server_default=""),
        sa.Column("asset", sa.String(32), server_default=""),
        sa.Column("amount_usd", sa.Float(), server_default="0"),
        sa.Column("facilitator", sa.String(64), server_default=""),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("receipt", sa.JSON(), server_default="{}"),
        sa.Column("success", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_x402_settlement_records_key", "x402_settlement_records", ["settlement_key"], unique=True
    )
    op.create_index(
        "ix_x402_settlement_records_payment_id", "x402_settlement_records", ["payment_id"]
    )
    op.create_index("ix_x402_settlement_records_tx_hash", "x402_settlement_records", ["tx_hash"])
    op.create_index(
        "ix_x402_settlement_records_created_at", "x402_settlement_records", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("x402_settlement_records")
    op.drop_table("x402_payment_records")
