"""notify.db 初期スキーマ (通知)

Revision ID: 0001
Revises:
Create Date: 2026-10-28

  event_cursors: detection.db の events をどこまで処理したか
  job_runs:      ジョブの実行記録 (常駐のスケジューラが最終成功時刻を引く)
  notifications: 送った通知 (dedupe_key で二重送信を防ぐ)
  alert_states:  取得停止などの監視項目の今の状態 (変わったときだけ通知する)
  issues:        GitHub Issue とパッケージのまとまりの対応
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_cursors",
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("last_seq", sa.Integer, nullable=False),
        sa.Column("epoch", sa.Text, nullable=False, server_default=""),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
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
    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("dedupe_key", sa.Text, nullable=False, unique=True),
        sa.Column("channel", sa.Text, nullable=False),  # line
        sa.Column("kind", sa.Text, nullable=False),  # finding / health / digest / test
        sa.Column("status", sa.Text, nullable=False),  # sent / skipped (送り先が未設定)
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("sent_at", sa.Text, nullable=False),
    )
    op.create_table(
        "alert_states",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("since", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_table(
        "issues",
        sa.Column("group_key", sa.Text, primary_key=True),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("state", sa.Text, nullable=False),  # open / closed
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body_hash", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    for table in ("issues", "alert_states", "notifications", "job_runs", "event_cursors"):
        op.drop_table(table)
