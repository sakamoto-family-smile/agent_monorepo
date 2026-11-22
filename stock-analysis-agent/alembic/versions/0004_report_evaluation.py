"""reports に評価用の列 (trace ID・総合判断・予測帯) を追加

Revision ID: 0004_report_evaluation
Revises: 0003_watchlist
Create Date: 2026-11-22

PROPOSAL-0014: 21 営業日後に方向と予測帯の当たり外れを採点するため、分析時点の判断と予測を残す。
既存のレポートは空のまま (後から埋めない)。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_report_evaluation"
down_revision: str | None = "0003_watchlist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: list[tuple[str, sa.types.TypeEngine]] = [
    ("trace_id", sa.String()),
    ("llm_model", sa.String()),
    ("stance", sa.String()),
    ("confidence", sa.String()),
    ("base_date", sa.String()),
    ("base_close", sa.Float()),
    ("forecast_horizon_days", sa.Integer()),
    ("forecast_end_date", sa.String()),
    ("forecast_bands", sa.Text()),
]


def upgrade() -> None:
    with op.batch_alter_table("reports") as batch:
        for name, type_ in _COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=True))
    op.create_index("ix_reports_trace_id", "reports", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_trace_id", table_name="reports")
    with op.batch_alter_table("reports") as batch:
        for name, _ in reversed(_COLUMNS):
            batch.drop_column(name)
