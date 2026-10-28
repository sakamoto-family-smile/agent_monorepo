"""例外をパッケージ名で指定する

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28

  exceptions.package: 対象のパッケージ名 (NULL ならその Advisory の全パッケージ)。
    purl はバージョンを含むので、更新のたびに例外が外れないよう名前で引き当てる
  exceptions.revoked_at: 取り消した時刻 (行は残して経緯を追えるようにする)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exceptions") as batch:
        batch.add_column(sa.Column("package", sa.Text))
        batch.add_column(sa.Column("revoked_at", sa.Text))
    op.create_index("ix_exceptions_advisory", "exceptions", ["advisory_id"])


def downgrade() -> None:
    op.drop_index("ix_exceptions_advisory", "exceptions")
    with op.batch_alter_table("exceptions") as batch:
        batch.drop_column("revoked_at")
        batch.drop_column("package")
