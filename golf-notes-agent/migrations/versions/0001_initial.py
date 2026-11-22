"""golf.db 初期スキーマ (PROPOSAL-0016 Phase 1: 受信と保存)

Revision ID: 0001
Revises:
Create Date: 2026-11-22

テーブルの役割:
  raw_events  LINE から届いたイベントの原本 (変更しない。重複は webhook_event_id で防ぐ)
  jobs        アプリ内のジョブ (動画・画像の取得など)。kind + ref_id で 1 件
  push_log    push の通数 (月の無料通数の管理)
  courses     コース名と表記ゆれ
  sessions    練習 / レッスン / ラウンド 1 回
  memos       メモ
  media       スイング動画・画像 (原本は data/media/)
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
        "raw_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("webhook_event_id", sa.Text, nullable=False, unique=True),
        sa.Column("line_message_id", sa.Text),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("message_type", sa.Text),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("is_redelivery", sa.Boolean, nullable=False),
        sa.Column("event_at", sa.Text, nullable=False),
        sa.Column("received_at", sa.Text, nullable=False),
    )
    op.create_index("ix_raw_events_user_event_at", "raw_events", ["user_id", "event_at"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("ref_id", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("polls", sa.Integer, nullable=False),
        sa.Column("next_run_at", sa.Text, nullable=False),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.UniqueConstraint("kind", "ref_id"),
    )
    op.create_index("ix_jobs_due", "jobs", ["status", "next_run_at"])

    op.create_table(
        "push_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("sent_at", sa.Text, nullable=False),
    )
    op.create_index("ix_push_log_sent_at", "push_log", ["sent_at"])

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("aliases_json", sa.Text, nullable=False),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("date", sa.Text, nullable=False),
        sa.Column("place", sa.Text),
        sa.Column("course_id", sa.Integer, sa.ForeignKey("courses.id")),
        sa.Column("provisional", sa.Boolean, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("started_at", sa.Text, nullable=False),
        sa.Column("last_activity_at", sa.Text, nullable=False),
        sa.Column("ended_at", sa.Text),
        sa.Column("end_reason", sa.Text),
    )
    op.create_index("ix_sessions_date_kind", "sessions", ["date", "kind"])

    op.create_table(
        "memos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("raw_event_id", sa.Integer, sa.ForeignKey("raw_events.id"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("deleted_at", sa.Text),
    )

    op.create_table(
        "media",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("raw_event_id", sa.Integer, sa.ForeignKey("raw_events.id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("path", sa.Text),
        sa.Column("sha256", sa.Text),
        sa.Column("size_bytes", sa.Integer),
        sa.Column("content_type", sa.Text),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("fps", sa.Float),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("angle", sa.Text),
        sa.Column("club", sa.Text),
        sa.Column("purpose", sa.Text),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("deleted_at", sa.Text),
    )


def downgrade() -> None:
    for name in ("media", "memos", "sessions", "courses", "push_log", "jobs", "raw_events"):
        op.drop_table(name)
