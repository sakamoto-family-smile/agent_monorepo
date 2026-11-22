"""テーブル定義 (SQLAlchemy Core)。スキーマの正は migrations/versions/ で、ここはクエリを書くための写し。

原本は raw_events (と data/raw/ の JSON)。ほかのテーブルはすべて原本から作り直せる派生データ。
時刻は UTC の ISO 文字列 (app.timeutil.iso)。日付は Asia/Tokyo の ``YYYY-MM-DD``。
"""
from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

raw_events = sa.Table(
    "raw_events",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    # 重複の判定はすべてのイベントに付く webhookEventId で行う (postback などにはメッセージ ID がない)
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

jobs = sa.Table(
    "jobs",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("ref_id", sa.Integer, nullable=False),
    sa.Column("status", sa.Text, nullable=False),  # pending | running | done | failed
    sa.Column("attempts", sa.Integer, nullable=False),
    sa.Column("polls", sa.Integer, nullable=False),
    sa.Column("next_run_at", sa.Text, nullable=False),
    sa.Column("last_error", sa.Text),
    sa.Column("created_at", sa.Text, nullable=False),
    sa.Column("updated_at", sa.Text, nullable=False),
    sa.UniqueConstraint("kind", "ref_id"),
)

push_log = sa.Table(
    "push_log",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("sent_at", sa.Text, nullable=False),
)

courses = sa.Table(
    "courses",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.Text, nullable=False, unique=True),
    sa.Column("aliases_json", sa.Text, nullable=False),
)

sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("kind", sa.Text, nullable=False),  # practice | lesson | round
    sa.Column("date", sa.Text, nullable=False),
    sa.Column("place", sa.Text),
    sa.Column("course_id", sa.Integer, sa.ForeignKey("courses.id")),
    # 1 = ボタンを押さずに作った仮のセッション (開いているセッションとしては扱わない)
    sa.Column("provisional", sa.Boolean, nullable=False),
    sa.Column("note", sa.Text),
    sa.Column("started_at", sa.Text, nullable=False),
    sa.Column("last_activity_at", sa.Text, nullable=False),
    sa.Column("ended_at", sa.Text),
    sa.Column("end_reason", sa.Text),  # manual | idle
)

memos = sa.Table(
    "memos",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id"), nullable=False),
    sa.Column("raw_event_id", sa.Integer, sa.ForeignKey("raw_events.id"), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("created_at", sa.Text, nullable=False),
    sa.Column("deleted_at", sa.Text),
)

media = sa.Table(
    "media",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id"), nullable=False),
    sa.Column("raw_event_id", sa.Integer, sa.ForeignKey("raw_events.id"), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),  # video | image
    sa.Column("status", sa.Text, nullable=False),  # pending | saved | failed
    sa.Column("path", sa.Text),  # data/ からの相対パス (media/YYYY/MM/<sha256>.<ext>)
    sa.Column("sha256", sa.Text),
    sa.Column("size_bytes", sa.Integer),
    sa.Column("content_type", sa.Text),
    sa.Column("width", sa.Integer),
    sa.Column("height", sa.Integer),
    sa.Column("fps", sa.Float),
    sa.Column("duration_ms", sa.Integer),
    sa.Column("angle", sa.Text),  # dtl | face_on | unknown
    sa.Column("club", sa.Text),
    sa.Column("purpose", sa.Text),  # 画像のみ: metrics | other (計測画像かどうか)
    sa.Column("source", sa.Text, nullable=False),  # line | folder
    sa.Column("created_at", sa.Text, nullable=False),
    sa.Column("deleted_at", sa.Text),
)

input_modes = sa.Table(
    "input_modes",
    metadata,
    sa.Column("user_id", sa.Text, primary_key=True),
    sa.Column("mode", sa.Text, nullable=False),  # metrics | video | score | course (memo は行なし)
    sa.Column("params_json", sa.Text, nullable=False),  # 動画モードの angle / club など
    sa.Column("expires_at", sa.Text, nullable=False),
    sa.Column("updated_at", sa.Text, nullable=False),
)

score_texts = sa.Table(
    "score_texts",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id"), nullable=False),
    sa.Column("raw_event_id", sa.Integer, sa.ForeignKey("raw_events.id"), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("created_at", sa.Text, nullable=False),
    sa.Column("deleted_at", sa.Text),
)


lesson_captures = sa.Table(
    "lesson_captures",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id"), nullable=False),
    sa.Column("source", sa.Text, nullable=False),  # text | image
    sa.Column("raw_event_id", sa.Integer, sa.ForeignKey("raw_events.id"), nullable=False),
    sa.Column("media_id", sa.Integer, sa.ForeignKey("media.id")),
    sa.Column("parser_version", sa.Text, nullable=False),
    sa.Column("ocr_model", sa.Text),
    sa.Column("raw_text", sa.Text, nullable=False),
    # confirmed (検算に引っかからない・人が確定した) | pending (確認待ち) | rejected
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("created_at", sa.Text, nullable=False),
    sa.Column("deleted_at", sa.Text),
)

launch_metrics = sa.Table(
    "launch_metrics",
    metadata,
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
    sa.Column("check_flags", sa.Text, nullable=False),  # JSON の配列 (検算に引っかかったコード)
)

metric_edits = sa.Table(
    "metric_edits",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("metric_id", sa.Integer, sa.ForeignKey("launch_metrics.id"), nullable=False),
    sa.Column("field", sa.Text, nullable=False),
    sa.Column("before", sa.Text),
    sa.Column("after", sa.Text),
    sa.Column("edited_at", sa.Text, nullable=False),
)
