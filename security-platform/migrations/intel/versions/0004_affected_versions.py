"""影響バージョンの列挙 (versions) を持つ

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27

  - record_affected.versions_json: 範囲 (ECOSYSTEM / SEMVER) で判定できない項目の versions。
    悪性パッケージ (MAL-) などは範囲を持たず、列挙されたバージョンでしか照合できない
  - v_advisory_affected に versions_json を足す (A2 への読み取り契約)
  - 0003 までは versions を捨てていたので、該当レコードの content_hash を空にして
    次の全量取得 (osv-full) で取り直させる
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_VIEW_WITH_VERSIONS = """
CREATE VIEW v_advisory_affected AS
SELECT r.advisory_id, f.record_id, f.ecosystem, f.name, f.purl, f.ranges_json, f.fixed_json,
  f.versions_json
FROM record_affected f JOIN osv_records r ON r.record_id = f.record_id
"""
_VIEW_WITHOUT_VERSIONS = """
CREATE VIEW v_advisory_affected AS
SELECT r.advisory_id, f.record_id, f.ecosystem, f.name, f.purl, f.ranges_json, f.fixed_json
FROM record_affected f JOIN osv_records r ON r.record_id = f.record_id
"""


def upgrade() -> None:
    op.add_column("record_affected", sa.Column("versions_json", sa.Text))
    op.execute("DROP VIEW IF EXISTS v_advisory_affected")
    op.execute(_VIEW_WITH_VERSIONS)
    op.execute(
        "UPDATE osv_records SET content_hash = '' WHERE record_id IN ("
        "SELECT f.record_id FROM record_affected f WHERE f.versions_count > 0 AND NOT EXISTS ("
        "SELECT 1 FROM json_each(f.ranges_json) r "
        "WHERE json_extract(r.value, '$.type') IN ('ECOSYSTEM', 'SEMVER')))"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_advisory_affected")
    op.execute(_VIEW_WITHOUT_VERSIONS)
    op.drop_column("record_affected", "versions_json")
