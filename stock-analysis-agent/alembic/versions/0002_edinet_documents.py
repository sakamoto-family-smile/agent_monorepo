"""edinet_documents (EDINET 文書 INDEX) を Cloud SQL に追加

Revision ID: 0002_edinet_documents
Revises: 0001_initial
Create Date: 2026-06-09

PROPOSAL-0011 P3-B: EDINET 有効化に伴い、P2-B で aiosqlite 据え置きにしていた
edinet_documents を shared Cloud SQL (Postgres) へ移行する。index batch (Cloud Run
Job) が書き込み、worker が分析時に読む。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_edinet_documents"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "edinet_documents",
        sa.Column("document_id", sa.String(), primary_key=True),
        sa.Column("edinet_code", sa.String(), nullable=False),
        sa.Column("securities_code", sa.String(), nullable=True),
        sa.Column("submitter_name", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("submit_date", sa.String(), nullable=False),
        sa.Column("period_end", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), server_default=sa.text("''")),
        sa.Column("withdrawal_status", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("disclosure_status", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("doc_info_edit_status", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("xbrl_flag", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("pdf_flag", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("attach_doc_flag", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cache_uri", sa.String(), nullable=True),
        sa.Column("cached_at", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.String(), nullable=False, server_default=_NOW),
        sa.Column("last_index_refreshed_at", sa.String(), nullable=False, server_default=_NOW),
    )
    op.create_index(
        "idx_edinet_docs_sec_code_date", "edinet_documents", ["securities_code", "submit_date"]
    )
    op.create_index(
        "idx_edinet_docs_edinet_code_date", "edinet_documents", ["edinet_code", "submit_date"]
    )
    op.create_index(
        "idx_edinet_docs_type_date", "edinet_documents", ["document_type", "submit_date"]
    )


def downgrade() -> None:
    op.drop_index("idx_edinet_docs_type_date", table_name="edinet_documents")
    op.drop_index("idx_edinet_docs_edinet_code_date", table_name="edinet_documents")
    op.drop_index("idx_edinet_docs_sec_code_date", table_name="edinet_documents")
    op.drop_table("edinet_documents")
