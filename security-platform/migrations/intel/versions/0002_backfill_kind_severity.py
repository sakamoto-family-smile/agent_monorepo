"""既存データの分類と深刻度を補正する

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26

  - advisories.kind: MAL- レコードを含む Advisory を 'malicious' にする
    (0001 時点の取り込みでは常に 'vulnerability' だった)
  - osv_records.severity_label: summary 先頭の "Important: " 等から補う (AlmaLinux 等)。
    該当 Advisory は advisories_dirty に積み、次回の取り込みで深刻度を再集計させる
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# src.intel.osv_record.severity_label_from_summary と同じ対応 (GLOB は大文字小文字を区別する)
_SUMMARY_LABELS = {"Critical": "CRITICAL", "Important": "HIGH", "Moderate": "MEDIUM", "Low": "LOW"}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE advisories SET kind = 'malicious' WHERE advisory_id IN "
        "(SELECT advisory_id FROM osv_records WHERE record_id LIKE 'MAL-%')"
    ))
    for prefix, label in _SUMMARY_LABELS.items():
        params = {"pattern": f"{prefix}: *", "label": label}
        conn.execute(sa.text(
            "INSERT OR IGNORE INTO advisories_dirty (advisory_id) SELECT DISTINCT advisory_id "
            "FROM osv_records WHERE severity_label IS NULL AND summary GLOB :pattern"
        ), params)
        conn.execute(sa.text(
            "UPDATE osv_records SET severity_label = :label "
            "WHERE severity_label IS NULL AND summary GLOB :pattern"
        ), params)


def downgrade() -> None:
    op.execute("UPDATE advisories SET kind = 'vulnerability' WHERE kind = 'malicious'")
