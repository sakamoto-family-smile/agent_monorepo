"""add line_user_links table for LINE Bot household mapping

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-21 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "line_user_links",
        sa.Column("line_user_id", sa.String(length=64), nullable=False),
        sa.Column("household_id", sa.String(length=64), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("line_user_id"),
    )
    op.create_index(
        "ix_line_user_links_household",
        "line_user_links",
        ["household_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_line_user_links_household", table_name="line_user_links")
    op.drop_table("line_user_links")
