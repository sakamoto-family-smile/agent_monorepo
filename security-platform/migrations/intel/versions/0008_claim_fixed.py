"""L4: 記事から作った Advisory の修正版 (claim_advisories.fixed_json)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-07

  記事の版の書き方 ("earlier than 1.84.1" など) を range にするようにしたので、range の fixed を
  v_advisory_affected.fixed_json に載せる (Finding の修正版と、自動改修の更新先に使う)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


_AFFECTED = """
CREATE VIEW v_advisory_affected AS
SELECT r.advisory_id, f.record_id, f.ecosystem, f.name, f.purl, f.ranges_json, f.fixed_json,
  f.versions_json
FROM record_affected f JOIN osv_records r ON r.record_id = f.record_id
UNION ALL
SELECT advisory_id, advisory_id, ecosystem, name, NULL, ranges_json, {fixed}, versions_json
FROM claim_advisories
"""


def upgrade() -> None:
    op.add_column("claim_advisories", sa.Column("fixed_json", sa.Text, nullable=False, server_default="[]"))
    op.execute("DROP VIEW IF EXISTS v_advisory_affected")
    op.execute(_AFFECTED.format(fixed="fixed_json"))


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_advisory_affected")
    op.execute(_AFFECTED.format(fixed="'[]'"))
    op.drop_column("claim_advisories", "fixed_json")
