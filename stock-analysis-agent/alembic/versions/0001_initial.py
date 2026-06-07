"""initial core schema (ticker_dictionary / price_cache / reports / alerts)

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-07

PROPOSAL-0011 P2-B: SQLite から shared Cloud SQL (Postgres) への移行。core 4 テーブル
のみ。edinet_documents は EDINET 有効化 (P3) まで aiosqlite 据え置きのため含めない。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "ticker_dictionary",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("aliases", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "market", sa.String(), nullable=False, server_default=sa.text("'unknown'")
        ),
        sa.Column("created_at", sa.String(), server_default=_NOW),
        sa.Column("updated_at", sa.String(), server_default=_NOW),
        sa.UniqueConstraint("company_name", "ticker", name="uq_ticker_dict"),
    )
    op.create_index(
        "idx_ticker_dict_name", "ticker_dictionary", ["company_name"]
    )

    op.create_table(
        "price_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("cached_at", sa.String(), server_default=_NOW),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.UniqueConstraint("ticker", "period", name="uq_price_cache"),
    )
    op.create_index("idx_price_cache_ticker", "price_cache", ["ticker", "period"])

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=True),
        sa.Column("report_data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), server_default=_NOW),
    )
    op.create_index("idx_reports_ticker", "reports", ["ticker"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("alert_type", sa.String(), nullable=False),
        sa.Column("condition_data", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Integer(), server_default=sa.text("1")),
        sa.Column("created_at", sa.String(), server_default=_NOW),
    )


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_index("idx_reports_ticker", table_name="reports")
    op.drop_table("reports")
    op.drop_index("idx_price_cache_ticker", table_name="price_cache")
    op.drop_table("price_cache")
    op.drop_index("idx_ticker_dict_name", table_name="ticker_dictionary")
    op.drop_table("ticker_dictionary")
