"""remediation のジョブの実行記録 (L5)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08

job_runs: 常駐のスケジューラが最終成功時刻を引く。detail には写しのコミットなどを JSON で残す
(notify は読み取り専用で開き、写しの更新が止まっていないかを見る)。
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
        "job_runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("job", sa.Text, nullable=False),
        sa.Column("started_at", sa.Text, nullable=False),
        sa.Column("finished_at", sa.Text),
        sa.Column("status", sa.Text, nullable=False),  # running / success / failed
        sa.Column("detail", sa.Text),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_job_runs_job_status", "job_runs", ["job", "status", "finished_at"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_job_status", "job_runs")
    op.drop_table("job_runs")
