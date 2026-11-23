"""絞り込みの語を足したので、絞り込みで外した記事を判定し直す

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-23

  src.intel.extraction.PREFILTER に RCE・認証回避などの語を足した。
  reason = 'prefilter' の行を消すと、次の抽出で今の語で絞り込み直す
  (当たれば依頼、外れれば skipped に戻る)。初回の取得の記事は元から対象外
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "DELETE FROM report_extractions WHERE status = 'skipped' AND reason = 'prefilter'"
    ))


def downgrade() -> None:
    pass  # 次の抽出で判定し直した結果が残る (戻す必要がない)
