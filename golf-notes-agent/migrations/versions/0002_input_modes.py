"""入力モードとスコアの原文 (PROPOSAL-0016 Phase 1 PR2)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22

  input_modes  いまの入力モード (リッチメニューで選ぶ)。最後の操作から 30 分で切れる
  score_texts  スコアモードで送ったテキストの原文 (抽出は Phase 2 で原本から行う)
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
        "input_modes",
        sa.Column("user_id", sa.Text, primary_key=True),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column("params_json", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_table(
        "score_texts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("raw_event_id", sa.Integer, sa.ForeignKey("raw_events.id"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("deleted_at", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("score_texts")
    op.drop_table("input_modes")
