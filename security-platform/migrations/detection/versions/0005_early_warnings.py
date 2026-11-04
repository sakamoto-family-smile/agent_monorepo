"""L4: 早期警告 (未確認の記事の主張と、使っているパッケージの名前が一致)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04

  early_warnings: 記事 (report_id) × パッケージ × サービス × 使っている部品 (purl) ごとに 1 件。
    Finding ではない (優先度・期限・Issue の対象にしない)。新しく当たったら warning.opened を出し、
    主張が OSV に載る・確認済みになる・部品を外すなどで当たらなくなったら closed にする
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "early_warnings",
        sa.Column("warning_id", sa.Text, primary_key=True),
        sa.Column("service_id", sa.Text, nullable=False),
        sa.Column("purl", sa.Text, nullable=False),
        sa.Column("report_id", sa.Text, nullable=False),
        sa.Column("claim_id", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),  # open / closed
        sa.Column("evidence_json", sa.Text, nullable=False),
        sa.Column("first_seen_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("closed_at", sa.Text),
    )
    op.create_index("ix_early_warnings_state", "early_warnings", ["state"])


def downgrade() -> None:
    op.drop_index("ix_early_warnings_state", "early_warnings")
    op.drop_table("early_warnings")
