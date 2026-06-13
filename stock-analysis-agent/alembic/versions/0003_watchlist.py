"""watchlist (ユーザー別マイリスト) を追加

Revision ID: 0003_watchlist
Revises: 0002_edinet_documents
Create Date: 2026-06-13

PROPOSAL-0012: user_id × ticker のマイリスト。LINE から 追加/削除/一覧 でき、
マイリストを対象にスクリーニングできる。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_watchlist"
down_revision: str | None = "0002_edinet_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), server_default=_NOW),
        sa.UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
    )
    op.create_index("ix_watchlist_user_id", "watchlist", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_user_id", table_name="watchlist")
    op.drop_table("watchlist")
