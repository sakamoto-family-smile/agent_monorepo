"""detection.db 初期スキーマ (A2 内部該当検知)

Revision ID: 0001
Revises:
Create Date: 2026-10-24

L0 ではスキーマのみ。書き込みは L2 (Matcher / Triage) から。
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
        "services",
        sa.Column("service_id", sa.Text, primary_key=True),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("owner", sa.Text),
        sa.Column("exposure", sa.Text, nullable=False),  # external / internal / none
        sa.Column("deployed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("auto_remediation", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("config_json", sa.Text, nullable=False),
        _ts("updated_at", nullable=False),
    )
    op.create_table(
        "sboms",
        sa.Column("sbom_id", sa.Text, primary_key=True),
        sa.Column("service_id", sa.Text, nullable=False, index=True),
        sa.Column("kind", sa.Text, nullable=False),  # source / image
        sa.Column("subject", sa.Text, nullable=False),  # lockfile hash / image digest
        sa.Column("path", sa.Text, nullable=False),  # data/sbom/... の CycloneDX
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.false()),
        _ts("generated_at", nullable=False),
    )
    op.create_table(
        "sbom_components",
        sa.Column("sbom_id", sa.Text, primary_key=True),
        sa.Column("purl", sa.Text, primary_key=True),
        sa.Column("ecosystem", sa.Text),
        sa.Column("name", sa.Text),
        sa.Column("version", sa.Text),
        sa.Column("is_direct", sa.Boolean),
    )
    op.create_table(
        "findings",
        sa.Column("finding_id", sa.Text, primary_key=True),
        sa.Column("service_id", sa.Text, nullable=False),
        sa.Column("advisory_id", sa.Text, nullable=False),
        sa.Column("purl", sa.Text, nullable=False),
        sa.Column("dependency_path", sa.Text),  # direct / transitive
        sa.Column("trigger", sa.Text, nullable=False),
        sa.Column("priority", sa.Text, nullable=False),
        _ts("due_at"),
        sa.Column("fix_type", sa.Text),
        sa.Column("fixed_version", sa.Text),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("evidence_json", sa.Text, nullable=False),
        _ts("first_seen_at", nullable=False),
        _ts("updated_at", nullable=False),
        _ts("closed_at"),
        sa.UniqueConstraint("service_id", "advisory_id", "purl", name="uq_findings_key"),
    )
    op.create_table(
        "finding_transitions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("finding_id", sa.Text, nullable=False, index=True),
        sa.Column("from_state", sa.Text),
        sa.Column("to_state", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("actor", sa.Text, nullable=False),
        _ts("occurred_at", nullable=False),
    )
    op.create_table(
        "exceptions",
        sa.Column("exception_id", sa.Text, primary_key=True),
        sa.Column("service_id", sa.Text, nullable=False),
        sa.Column("advisory_id", sa.Text, nullable=False),
        sa.Column("purl", sa.Text),
        sa.Column("kind", sa.Text, nullable=False),  # false_positive / risk_accepted
        sa.Column("reason", sa.Text, nullable=False),
        _ts("expires_at"),
        _ts("created_at", nullable=False),
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
    for table in (
        "db_info", "events", "event_cursors", "exceptions", "finding_transitions",
        "findings", "sbom_components", "sboms", "services",
    ):
        op.drop_table(table)
