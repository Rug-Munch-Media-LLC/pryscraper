"""add hosting_invoices — persist hosting revenue invoices (audit item #1)

Revision ID: 0004
Revises: b3b4faf8e50d
Create Date: 2026-09-02 00:00:00.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0004"
down_revision: str | None = "b3b4faf8e50d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hosting_invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), server_default="signup", nullable=False),
        sa.Column("plan_tier", sa.String(32), nullable=False),
        sa.Column("user_email", sa.String(256), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("instance_id", sa.String(64), server_default=""),
        sa.Column("payment_method", sa.String(32), server_default="x402", nullable=False),
        sa.Column("amount_usd", sa.Float(), nullable=False),
        sa.Column("amount_atomic", sa.String(64), server_default="0", nullable=False),
        sa.Column("chain", sa.String(32), server_default="", nullable=False),
        sa.Column("pay_to", sa.String(128), server_default="", nullable=False),
        sa.Column("asset", sa.String(16), server_default="USDC", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("payment", sa.JSON(), server_default="{}"),
        sa.Column("x402_body", sa.JSON(), server_default="{}"),
        sa.Column("credited_reference", sa.String(256), server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hosting_invoices_invoice_id", "hosting_invoices", ["invoice_id"], unique=True
    )
    op.create_index("ix_hosting_invoices_user_email", "hosting_invoices", ["user_email"])
    op.create_index("ix_hosting_invoices_status", "hosting_invoices", ["status"])
    op.create_index(
        "ix_hosting_invoices_user_created",
        "hosting_invoices",
        ["user_email", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_hosting_invoices_user_created", table_name="hosting_invoices")
    op.drop_index("ix_hosting_invoices_status", table_name="hosting_invoices")
    op.drop_index("ix_hosting_invoices_user_email", table_name="hosting_invoices")
    op.drop_index("ix_hosting_invoices_invoice_id", table_name="hosting_invoices")
    op.drop_table("hosting_invoices")
