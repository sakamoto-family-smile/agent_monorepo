"""L4: 記事から抜き出した「危ないパッケージ」の主張

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-01

  report_extractions: 記事ごとの抽出の状態。本文 (content_hash) が変わったらやり直す
                      status: skipped (前段の絞り込みで対象外) / queued (extractor 待ち) / done / failed
  report_claims:      抜き出した主張 1 件ごと。grounded = 0 は原文と突き合わせて根拠が見つからなかったもの
                      (照合・通知には使わない。抽出の評価のために残す)。記事を抽出し直したら入れ替える
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_extractions",
        sa.Column("report_id", sa.Text, primary_key=True),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("job_id", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("provider", sa.Text),
        sa.Column("model", sa.Text),
        sa.Column("prompt_version", sa.Text),
        sa.Column("about_specific_packages", sa.Boolean),
        sa.Column("claims", sa.Integer, nullable=False, server_default="0"),
        sa.Column("grounded_claims", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("queued_at", sa.Text),
        sa.Column("finished_at", sa.Text),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_index("ix_report_extractions_status", "report_extractions", ["status", "queued_at"])
    op.create_table(
        "report_claims",
        sa.Column("claim_id", sa.Text, primary_key=True),
        sa.Column("report_id", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("ecosystem", sa.Text, nullable=False),
        sa.Column("package", sa.Text, nullable=False),
        sa.Column("versions_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("identifiers_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("quote", sa.Text, nullable=False),
        sa.Column("grounded", sa.Boolean, nullable=False),
        sa.Column("notes_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("extracted_at", sa.Text, nullable=False),
    )
    op.create_index("ix_report_claims_report", "report_claims", ["report_id"])
    op.create_index("ix_report_claims_package", "report_claims", ["ecosystem", "package"])


def downgrade() -> None:
    op.drop_index("ix_report_claims_package", "report_claims")
    op.drop_index("ix_report_claims_report", "report_claims")
    op.drop_table("report_claims")
    op.drop_index("ix_report_extractions_status", "report_extractions")
    op.drop_table("report_extractions")
