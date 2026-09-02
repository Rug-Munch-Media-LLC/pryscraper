"""add hosting invoice email verification columns (audit item #4)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02 00:00:00.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hosting_invoices",
        sa.Column("verification_code", sa.String(16), server_default="", nullable=False),
    )
    op.add_column(
        "hosting_invoices",
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("hosting_invoices", "email_verified")
    op.drop_column("hosting_invoices", "verification_code")
