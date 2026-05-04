"""sessions / conversations / conversation_messages (Phase 3-A)

Phase 3 で追加する LLM 相談 + 自然言語分析の永続化テーブル。

- sessions          : line_user_id 単位の現在モード (normal / consulting) を保持
- conversations     : 1 つの相談セッション (begin → end までの会話の塊)
- conversation_messages : 個別メッセージ (user / assistant / tool_use / tool_result)

将来の機能改善のため:
- conversation_messages.capability_gap で「対応できなかった理由」をタグで記録
  ("asked_clarification" / "out_of_scope" / "data_missing" / "tool_error" 等)
- token / cost を message ごとに記録 (input_tokens / output_tokens / cache_read_tokens)

Revision ID: 0002_session_conversation
Revises: 0001_initial
Create Date: 2026-05-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_session_conversation"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- sessions ----
    op.create_table(
        "sessions",
        sa.Column("line_user_id", sa.String(), primary_key=True),
        sa.Column("family_id", sa.String(), nullable=False),
        sa.Column(
            "mode", sa.String(), nullable=False, server_default="normal"
        ),
        sa.Column("consulting_since", sa.String(), nullable=True),
        sa.Column("current_conversation_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index(
        "idx_sessions_family_mode",
        "sessions",
        ["family_id", "mode"],
    )

    # ---- conversations ----
    op.create_table(
        "conversations",
        sa.Column("conversation_id", sa.String(), primary_key=True),
        sa.Column("family_id", sa.String(), nullable=False),
        sa.Column("line_user_id", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("ended_at", sa.String(), nullable=True),
        sa.Column(
            "message_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("system_prompt_version", sa.String(), nullable=True),
        sa.Column(
            "total_input_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_output_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_cache_read_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "idx_conversations_family_started",
        "conversations",
        ["family_id", "started_at"],
    )

    # ---- conversation_messages ----
    op.create_table(
        "conversation_messages",
        sa.Column("message_id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        # role: user / assistant / tool_use / tool_result
        sa.Column("role", sa.String(), nullable=False),
        # content: text の場合は user message / assistant 返答。
        # tool_use の場合は tool 名 + 引数 JSON。
        # tool_result の場合は tool 出力テキスト。
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        # LLM 関連メタデータ (assistant message で記録)
        sa.Column("llm_model", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        # tool_use 関連
        sa.Column("tool_name", sa.String(), nullable=True),
        # 機能改善のためのタグ (asked_clarification / out_of_scope /
        # data_missing / tool_error / refused / completed)
        sa.Column("capability_gap", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_messages_conversation_created",
        "conversation_messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "idx_messages_capability_gap",
        "conversation_messages",
        ["capability_gap"],
        postgresql_where=sa.text("capability_gap IS NOT NULL"),
        sqlite_where=sa.text("capability_gap IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_messages_capability_gap", table_name="conversation_messages")
    op.drop_index(
        "idx_messages_conversation_created", table_name="conversation_messages"
    )
    op.drop_table("conversation_messages")
    op.drop_index("idx_conversations_family_started", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("idx_sessions_family_mode", table_name="sessions")
    op.drop_table("sessions")
