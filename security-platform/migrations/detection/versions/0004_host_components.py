"""開発 PC のツールの履歴

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31

  host_components: 開発 PC (data/sbom/hosts/) で見つけた部品ごとに、最初と最後に見た時刻。
    悪性パッケージの登録は数日遅れるので、今は入っていない (更新で消えた) 版も
    HOST_HISTORY_DAYS のあいだは悪性パッケージと照合する。時刻は一覧を作った時刻 (照合した時刻ではない)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "host_components",
        sa.Column("host_id", sa.Text, primary_key=True),
        sa.Column("purl", sa.Text, primary_key=True),
        sa.Column("ecosystem", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("is_direct", sa.Boolean, nullable=False),
        sa.Column("first_seen_at", sa.Text, nullable=False),
        sa.Column("last_seen_at", sa.Text, nullable=False),
    )
    op.create_index("ix_host_components_last_seen", "host_components", ["host_id", "last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_host_components_last_seen", "host_components")
    op.drop_table("host_components")
