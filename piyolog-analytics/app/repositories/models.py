"""SQLAlchemy declarative models。

旧 `repositories/schema.sql` の DDL を Python で表現したもの。
Alembic migration の autogenerate ターゲットとしても使う。
"""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """全モデル共通のベース。Alembic の MetaData ターゲットに使う。"""


class PiyologEvent(Base):
    __tablename__ = "piyolog_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    family_id: Mapped[str] = mapped_column(String, nullable=False)
    source_user_id: Mapped[str] = mapped_column(String, nullable=False)
    child_id: Mapped[str] = mapped_column(String, nullable=False, default="default")
    event_timestamp: Mapped[str] = mapped_column(String, nullable=False)  # ISO8601 +09:00
    event_date: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD JST
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    volume_ml: Mapped[float | None] = mapped_column(Float, nullable=True)
    left_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    right_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    head_circumference_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    import_batch_id: Mapped[str] = mapped_column(String, nullable=False)
    imported_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("idx_events_family_date", "family_id", "event_date"),
        Index("idx_events_family_type_date", "family_id", "event_type", "event_date"),
        Index("idx_events_batch", "import_batch_id"),
    )


class ImportBatchRow(Base):
    __tablename__ = "import_batches"

    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    family_id: Mapped[str] = mapped_column(String, nullable=False)
    source_user_id: Mapped[str] = mapped_column(String, nullable=False)
    source_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_hash: Mapped[str] = mapped_column(String, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_at: Mapped[str] = mapped_column(String, nullable=False)
    rolled_back_at: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_batches_family", "family_id", "imported_at"),
        # active な (rolled_back_at IS NULL) 単位での重複検知用 partial unique index。
        # SQLite / Postgres ともに `WHERE rolled_back_at IS NULL` 構文をサポート。
        Index(
            "idx_batches_hash_dedup",
            "family_id",
            "raw_text_hash",
            unique=True,
            sqlite_where=text("rolled_back_at IS NULL"),
            postgresql_where=text("rolled_back_at IS NULL"),
        ),
    )


# ---- Phase 3: 相談 + 自然言語分析 ----


class SessionRow(Base):
    """LINE user 単位の現在モード。"""

    __tablename__ = "sessions"

    line_user_id: Mapped[str] = mapped_column(String, primary_key=True)
    family_id: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    consulting_since: Mapped[str | None] = mapped_column(String, nullable=True)
    current_conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (Index("idx_sessions_family_mode", "family_id", "mode"),)


class ConversationRow(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String, primary_key=True)
    family_id: Mapped[str] = mapped_column(String, nullable=False)
    line_user_id: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    ended_at: Mapped[str | None] = mapped_column(String, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    total_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("idx_conversations_family_started", "family_id", "started_at"),)


class ConversationMessageRow(Base):
    """会話の 1 メッセージ。

    role:
      - user           : ユーザーの発話
      - assistant      : LLM の text 応答
      - tool_use       : LLM の tool call (content に tool 名 + JSON 引数)
      - tool_result    : tool 実行結果 (content に出力テキスト)
    capability_gap (assistant message のみ意味を持つタグ):
      - asked_clarification : 不足情報を質問した
      - out_of_scope        : 対応範囲外と判断
      - data_missing        : 必要なデータが piyolog 側に無かった
      - tool_error          : tool 実行失敗
      - refused             : 安全ガード等で拒否
      - completed           : 完答 (default)
    """

    __tablename__ = "conversation_messages"

    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String, nullable=True)
    capability_gap: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index(
            "idx_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index(
            "idx_messages_capability_gap",
            "capability_gap",
            sqlite_where=text("capability_gap IS NOT NULL"),
            postgresql_where=text("capability_gap IS NOT NULL"),
        ),
    )
