"""remediation.db 初期スキーマ (B 改修・検証)

Revision ID: 0001
Revises:
Create Date: 2026-10-24

L0 ではスキーマのみ。書き込みは L3 から。
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.Text, nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("finding_id", sa.Text, nullable=False, index=True),
        sa.Column("service_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("branch", sa.Text),
        sa.Column("pr_url", sa.Text),
        sa.Column("package_json", sa.Text),  # 承認パッケージ
        _ts("started_at", nullable=False),
        _ts("finished_at"),
    )
    op.create_table(
        "run_steps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Text, nullable=False, index=True),
        sa.Column("step", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("detail_json", sa.Text, nullable=False),
        sa.Column("log_path", sa.Text),
        _ts("started_at", nullable=False),
        _ts("finished_at"),
    )
    op.create_table(
        "event_cursors",
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("last_seq", sa.Integer, nullable=False),
        # 発行側 DB の db_info.epoch。DB を作り直すと変わり、カーソルは 0 から読み直す
        sa.Column("epoch", sa.Text, nullable=False, server_default=""),
        _ts("updated_at", nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("seq", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Text, nullable=False, unique=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        _ts("occurred_at", nullable=False),
        # AUTOINCREMENT: 末尾の行を消しても seq を再利用しない (受信側の読み飛ばし防止)
        sqlite_autoincrement=True,
    )
    _create_db_info()


def _create_db_info() -> None:
    """DB ファイル固有の epoch。作り直すと変わるので、受信側は seq の振り直しを検知できる。"""
    op.create_table(
        "db_info",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    op.execute(f"INSERT INTO db_info (key, value) VALUES ('epoch', '{uuid.uuid4().hex}')")


def downgrade() -> None:
    for table in ("db_info", "events", "event_cursors", "run_steps", "runs"):
        op.drop_table(table)
