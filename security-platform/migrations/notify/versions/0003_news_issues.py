"""重大ニュース (PROPOSAL-0015): 週次まとめの GitHub Issue

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22

  週 (ISO 週, YYYY-Www) ごとに 1 件の Issue を立てた記録。翌週の Issue を立てたら前の週を閉じる
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_issues",
        sa.Column("week", sa.Text, primary_key=True),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("state", sa.Text, nullable=False),  # open / closed
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("closed_at", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("news_issues")
