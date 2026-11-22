"""重大ニュース (PROPOSAL-0015): 送った記事・KEV の記録

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22

  日次の重大ニュースで扱った記事 (report:<report_id>) と KEV (kev:<CVE>) を記録し、翌日以降に重ねて送らない。
  載せきれず「ほか n 件」にしたものも扱い済みにする (週次まとめで一覧にする)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("item_key", sa.Text, primary_key=True),
        sa.Column("dedupe_key", sa.Text, nullable=False),  # 扱った日次の通知 (notifications.dedupe_key)
        sa.Column("shown", sa.Boolean, nullable=False),  # 本文に載せたか (False は「ほか n 件」)
        sa.Column("handled_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("news_items")
