"""upstream から深刻度を引き継げる Advisory を再集計待ちに積む

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26

  深刻度を持たない脆弱性の Advisory のうち、レコードに upstream があるもの
  (Chainguard・Wolfi の CVE なしレコード、USN・DSA などのまとめ告知) を
  advisories_dirty に積み、次回の取り込みで upstream の深刻度を引き継がせる
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT OR IGNORE INTO advisories_dirty (advisory_id) "
        "SELECT DISTINCT a.advisory_id FROM advisories a "
        "JOIN osv_records r ON r.advisory_id = a.advisory_id "
        "JOIN record_aliases x ON x.record_id = r.record_id AND x.relation = 'upstream' "
        "WHERE a.severity IS NULL AND a.kind = 'vulnerability'"
    )


def downgrade() -> None:
    # 積んだ再集計待ちは次回の取り込みで消化されるだけなので戻すものはない
    pass
