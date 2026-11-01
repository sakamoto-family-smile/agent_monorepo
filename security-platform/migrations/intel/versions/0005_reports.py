"""L4: 注意喚起・公式の告知・調査会社のフィードの記事

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01

  feeds:   config/feeds.yaml のフィードごとの取得状態 (条件付き GET の ETag・最終成功・失敗)。
           設定から消したフィードは enabled = 0 にして監視をやめる (記事は残す)
  reports: フィードの記事 1 件ごと。report_id はフィードと guid から決める。
           initial = 1 はフィードを初めて取得したときに既にあった記事 (古い記事で通知しない)
           本文 (summary) は HTML をテキストにしたもの。原文は raw_ref (data/raw/reports/) にある
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
        "feeds",
        sa.Column("feed_id", sa.Text, primary_key=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("trust", sa.Text, nullable=False),
        sa.Column("lang", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("etag", sa.Text),
        sa.Column("last_modified", sa.Text),
        sa.Column("content_sha256", sa.Text),
        sa.Column("last_success_at", sa.Text),
        sa.Column("last_error", sa.Text),
        sa.Column("last_error_at", sa.Text),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_table(
        "reports",
        sa.Column("report_id", sa.Text, primary_key=True),
        sa.Column("feed_id", sa.Text, nullable=False),
        sa.Column("guid", sa.Text, nullable=False),
        sa.Column("url", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("links_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("trust", sa.Text, nullable=False),
        sa.Column("lang", sa.Text, nullable=False),
        sa.Column("published_at", sa.Text),
        sa.Column("initial", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("raw_ref", sa.Text, nullable=False),
        sa.Column("first_seen_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_index("ix_reports_feed_seen", "reports", ["feed_id", "first_seen_at"])
    op.create_index("ix_reports_seen", "reports", ["first_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_reports_seen", "reports")
    op.drop_index("ix_reports_feed_seen", "reports")
    op.drop_table("reports")
    op.drop_table("feeds")
