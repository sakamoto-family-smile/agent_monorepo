"""add canonical_category to transactions and household profile tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-20 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- F1: transactions に canonical カラム ---
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(
            sa.Column(
                "canonical_category",
                sa.String(length=64),
                nullable=False,
                server_default="other",
            )
        )
        batch.add_column(
            sa.Column(
                "expense_type",
                sa.String(length=16),
                nullable=False,
                server_default="variable",
            )
        )
    op.create_index(
        "ix_transactions_household_canonical",
        "transactions",
        ["household_id", "canonical_category"],
        unique=False,
    )

    # --- F2: 世帯プロファイル 3 テーブル ---
    op.create_table(
        "household_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("household_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column(
            "employment_status",
            sa.String(length=32),
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "annual_income",
            sa.Numeric(precision=14, scale=0),
            nullable=False,
            server_default="0",
        ),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_members_household", "household_members", ["household_id"], unique=False)

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("household_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Numeric(precision=16, scale=0), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_household", "assets", ["household_id"], unique=False)

    op.create_table(
        "liabilities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("household_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("balance", sa.Numeric(precision=16, scale=0), nullable=False),
        sa.Column(
            "interest_rate",
            sa.Numeric(precision=6, scale=4),
            nullable=False,
            server_default="0",
        ),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_liabilities_household", "liabilities", ["household_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_liabilities_household", table_name="liabilities")
    op.drop_table("liabilities")
    op.drop_index("ix_assets_household", table_name="assets")
    op.drop_table("assets")
    op.drop_index("ix_members_household", table_name="household_members")
    op.drop_table("household_members")
    op.drop_index("ix_transactions_household_canonical", table_name="transactions")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("expense_type")
        batch.drop_column("canonical_category")
