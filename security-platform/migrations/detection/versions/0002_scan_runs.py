"""照合の実行記録

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27

  scan_runs: 照合ジョブの開始・終了・件数。常駐のスケジューラが最終成功時刻を引く
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
        "scan_runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("job", sa.Text, nullable=False),
        sa.Column("started_at", sa.Text, nullable=False),
        sa.Column("finished_at", sa.Text),
        sa.Column("status", sa.Text, nullable=False),  # running / success / failed
        sa.Column("services", sa.Integer, nullable=False, server_default="0"),
        sa.Column("components", sa.Integer, nullable=False, server_default="0"),
        sa.Column("open_findings", sa.Integer, nullable=False, server_default="0"),
        sa.Column("opened", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("resolved", sa.Integer, nullable=False, server_default="0"),
        sa.Column("warnings_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_scan_runs_job_status", "scan_runs", ["job", "status", "finished_at"])
    op.create_index("ix_findings_state", "findings", ["state", "priority"])


def downgrade() -> None:
    op.drop_index("ix_findings_state", "findings")
    op.drop_table("scan_runs")
