"""自動改修の記録 (L5: 依存の更新 PR)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08

runs:          改修 1 回 (サービス 1 つ・PR 1 本)。0001 の runs は 1 Finding 1 行の想定で、まだ使っていないので作り直す
run_steps:     状態の変化の記録 (0001 のまま)
attempts:      上げられなかった (パッケージ, 版)。同じ版では二度と試さない (修正版が変われば試す)
service_modes: bundle (まとめて 1 本) / single (1 つずつ)。まとめた PR の CI が落ちたら single にする
state:         通知の重複を避けるための小さな状態 (トークンの期限の知らせなど)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.Text, nullable=nullable)


def upgrade() -> None:
    op.drop_table("runs")
    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("service_id", sa.Text, nullable=False),
        sa.Column("lockfile", sa.Text, nullable=False),  # モノレポのルートからのパス
        # queued → pr_open → merged → landed → verified (途中で止まると update_failed / guard_failed /
        # ci_failed / conflict / closed / not_resolved / error)
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("mode", sa.Text, nullable=False),  # bundle / single
        sa.Column("manual", sa.Boolean, nullable=False, server_default=sa.false()),  # P1: 人がマージする
        sa.Column("base_sha", sa.Text, nullable=False),
        sa.Column("branch", sa.Text),
        sa.Column("pr_number", sa.Integer),
        sa.Column("pr_url", sa.Text),
        sa.Column("head_sha", sa.Text),
        sa.Column("merge_sha", sa.Text),
        sa.Column("deploy_status", sa.Text),  # none / pending / success / failed
        sa.Column("packages_json", sa.Text, nullable=False),  # [{name, current, target, priority, finding_ids}]
        sa.Column("detail_json", sa.Text, nullable=False, server_default="{}"),
        _ts("created_at", nullable=False),
        _ts("updated_at", nullable=False),
        _ts("finished_at"),
    )
    op.create_index("ix_runs_service_status", "runs", ["service_id", "status"])
    op.create_table(
        "attempts",
        sa.Column("service_id", sa.Text, primary_key=True),
        sa.Column("package", sa.Text, primary_key=True),
        sa.Column("target", sa.Text, primary_key=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("run_id", sa.Text, nullable=False),
        _ts("created_at", nullable=False),
    )
    op.create_table(
        "service_modes",
        sa.Column("service_id", sa.Text, primary_key=True),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        _ts("updated_at", nullable=False),
    )
    op.create_table(
        "state",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        _ts("updated_at", nullable=False),
    )


def downgrade() -> None:
    for table in ("state", "service_modes", "attempts"):
        op.drop_table(table)
    op.drop_index("ix_runs_service_status", "runs")
    op.drop_table("runs")
    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("finding_id", sa.Text, nullable=False, index=True),
        sa.Column("service_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("branch", sa.Text),
        sa.Column("pr_url", sa.Text),
        sa.Column("package_json", sa.Text),
        _ts("started_at", nullable=False),
        _ts("finished_at"),
    )
