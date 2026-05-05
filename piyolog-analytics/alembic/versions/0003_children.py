"""children テーブル (Phase 4-B)

家族ごとの子情報を DB 化する。Phase 3 までは env `CHILD_BIRTH_DATE` で
プロセス全体に 1 つの生年月日を持たせていたが、複数家族 / 複数子に
拡張するには env では足りないので per-family のレコードに移す。

- children.child_id   : 家族内ローカル ID (default: "default") — piyolog_events.child_id と紐付く
- children.family_id  : 家族 ID (events と同じ scoping)
- children.birth_date : YYYY-MM-DD (空文字なら未設定)
- children.name       : 表示用の名前 (任意)

LINE Postback の datetime picker → settings UI から書き込まれる前提。
context_builder は env が空ならこのテーブルから読む (env が settings より優先)。

Revision ID: 0003_children
Revises: 0002_session_conversation
Create Date: 2026-05-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_children"
down_revision: str | None = "0002_session_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "children",
        sa.Column("family_id", sa.String(), primary_key=True),
        sa.Column("child_id", sa.String(), primary_key=True),
        sa.Column("birth_date", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("children")
