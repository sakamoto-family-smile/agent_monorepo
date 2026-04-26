"""initial schema (piyolog_events + import_batches)

旧 `repositories/schema.sql` の DDL を Alembic 化したもの。
SQLite / Postgres 両対応 (partial unique index は両方対応している)。

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "piyolog_events",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("family_id", sa.String(), nullable=False),
        sa.Column("source_user_id", sa.String(), nullable=False),
        sa.Column("child_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("event_timestamp", sa.String(), nullable=False),
        sa.Column("event_date", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("volume_ml", sa.Float(), nullable=True),
        sa.Column("left_minutes", sa.Integer(), nullable=True),
        sa.Column("right_minutes", sa.Integer(), nullable=True),
        sa.Column("sleep_minutes", sa.Integer(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("head_circumference_cm", sa.Float(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("import_batch_id", sa.String(), nullable=False),
        sa.Column("imported_at", sa.String(), nullable=False),
    )
    op.create_index("idx_events_family_date", "piyolog_events", ["family_id", "event_date"])
    op.create_index(
        "idx_events_family_type_date",
        "piyolog_events",
        ["family_id", "event_type", "event_date"],
    )
    op.create_index("idx_events_batch", "piyolog_events", ["import_batch_id"])

    op.create_table(
        "import_batches",
        sa.Column("batch_id", sa.String(), primary_key=True),
        sa.Column("family_id", sa.String(), nullable=False),
        sa.Column("source_user_id", sa.String(), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=True),
        sa.Column("raw_text_hash", sa.String(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_at", sa.String(), nullable=False),
        sa.Column("rolled_back_at", sa.String(), nullable=True),
    )
    op.create_index("idx_batches_family", "import_batches", ["family_id", "imported_at"])

    # active レコードに対する partial unique。SQLite / Postgres ともに `WHERE` 構文をサポート。
    op.create_index(
        "idx_batches_hash_dedup",
        "import_batches",
        ["family_id", "raw_text_hash"],
        unique=True,
        sqlite_where=sa.text("rolled_back_at IS NULL"),
        postgresql_where=sa.text("rolled_back_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_batches_hash_dedup", table_name="import_batches")
    op.drop_index("idx_batches_family", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_index("idx_events_batch", table_name="piyolog_events")
    op.drop_index("idx_events_family_type_date", table_name="piyolog_events")
    op.drop_index("idx_events_family_date", table_name="piyolog_events")
    op.drop_table("piyolog_events")
