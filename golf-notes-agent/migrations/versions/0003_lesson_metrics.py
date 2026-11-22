"""レッスン計測 (PROPOSAL-0016 Phase 1 PR3, §4.2.1)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22

  lesson_captures  1 回の取り込み (計測テキスト 1 通。Phase 2 の OCR では画像 1 枚)
  launch_metrics   1 球 = 1 行。符号は「右・オープン・イントゥアウトが正」。画面の表記は labels_json
  metric_edits     訂正の履歴
  v_launch_metrics face_to_path_deg (フェース − 軌道) を足したビュー
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lesson_captures",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("raw_event_id", sa.Integer, sa.ForeignKey("raw_events.id"), nullable=False),
        sa.Column("media_id", sa.Integer, sa.ForeignKey("media.id")),
        sa.Column("parser_version", sa.Text, nullable=False),
        sa.Column("ocr_model", sa.Text),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("deleted_at", sa.Text),
    )
    op.create_table(
        "launch_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("capture_id", sa.Integer, sa.ForeignKey("lesson_captures.id"), nullable=False),
        sa.Column("shot_no", sa.Integer, nullable=False),
        sa.Column("shot_at", sa.Text, nullable=False),
        sa.Column("club", sa.Text),
        sa.Column("total_yd", sa.Float),
        sa.Column("carry_yd", sa.Float),
        sa.Column("run_yd", sa.Float),
        sa.Column("club_speed_mps", sa.Float),
        sa.Column("ball_speed_mps", sa.Float),
        sa.Column("smash_factor", sa.Float),
        sa.Column("apex_m", sa.Float),
        sa.Column("descent_angle_deg", sa.Float),
        sa.Column("offline_yd", sa.Float),
        sa.Column("launch_v_deg", sa.Float),
        sa.Column("backspin_rpm", sa.Float),
        sa.Column("launch_h_deg", sa.Float),
        sa.Column("sidespin_rpm", sa.Float),
        sa.Column("club_path_deg", sa.Float),
        sa.Column("face_angle_deg", sa.Float),
        sa.Column("labels_json", sa.Text, nullable=False),
        sa.Column("extra_json", sa.Text, nullable=False),
        sa.Column("confidence_json", sa.Text),
        sa.Column("check_flags", sa.Text, nullable=False),
        sa.UniqueConstraint("capture_id", "shot_no"),
    )
    op.create_index("ix_launch_metrics_club_shot_at", "launch_metrics", ["club", "shot_at"])
    op.create_table(
        "metric_edits",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("metric_id", sa.Integer, sa.ForeignKey("launch_metrics.id"), nullable=False),
        sa.Column("field", sa.Text, nullable=False),
        sa.Column("before", sa.Text),
        sa.Column("after", sa.Text),
        sa.Column("edited_at", sa.Text, nullable=False),
    )
    # 取り消した取り込み・確定していない (rejected) 取り込みは含めない
    op.execute(
        """
        CREATE VIEW v_launch_metrics AS
        SELECT m.*, c.session_id, c.status AS capture_status,
               m.face_angle_deg - m.club_path_deg AS face_to_path_deg
        FROM launch_metrics m
        JOIN lesson_captures c ON c.id = m.capture_id
        WHERE c.deleted_at IS NULL AND c.status = 'confirmed'
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW v_launch_metrics")
    op.drop_table("metric_edits")
    op.drop_table("launch_metrics")
    op.drop_table("lesson_captures")
