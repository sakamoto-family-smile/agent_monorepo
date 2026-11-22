"""重大ニュース (PROPOSAL-0015): 記事の brief (重大度・日本語の要約・分類)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-22

  extractor の出力に足した brief を report_extractions に持つ。notify が日次・週次の重大ニュースに使う。
  列の追加だけ (既存の行は NULL = brief なし)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


COLUMNS = ("severity", "summary_ja", "topics_json", "brief_identifiers_json")


def upgrade() -> None:
    for col in COLUMNS:
        op.add_column("report_extractions", sa.Column(col, sa.Text))
    op.create_index("ix_report_extractions_brief", "report_extractions", ["severity", "finished_at"])


def downgrade() -> None:
    op.drop_index("ix_report_extractions_brief", "report_extractions")
    for col in reversed(COLUMNS):
        op.drop_column("report_extractions", col)
