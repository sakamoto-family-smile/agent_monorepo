"""L4: 記事の主張の確度と、照合に使う Advisory (claim_advisories)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-04

  report_claims に確度を足す (src/intel/claims.py が抽出のたびに判定し直す)
    status: confirmed (一次情報で裏付け) / unconfirmed (裏付けなし。照合には使わない) /
            superseded (OSV に載った。照合は OSV に任せる) / ungrounded (原文と突き合わせて根拠なし)
    status_reason・linked_json (対応する OSV の Advisory)・advisory_id (claim_advisories に載せた ID)
  claim_advisories: confirmed の主張をパッケージごとにまとめた Advisory (SPI-...)。
                    v_advisories・v_advisory_affected に合わせて載せ、A2 の照合はそのまま使う。
                    主張が無くなったら withdrawn = 1 (Finding は次の照合で閉じる)
  v_report_claims: A2 の早期警告 (未確認でも使っているパッケージと同じ名前) のための読み取り契約
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_ADVISORIES = """
CREATE VIEW v_advisories AS
SELECT
  a.advisory_id, a.kind, a.cves_json, a.summary, a.cvss_score, a.cvss_vector, a.severity,
  a.published_at, a.modified_at, a.withdrawn, a.record_count, a.first_seen_at, a.updated_at,
  EXISTS (
    SELECT 1 FROM advisory_cves c JOIN kev_entries k ON k.cve = c.cve
    WHERE c.advisory_id = a.advisory_id
  ) AS kev,
  (SELECT MIN(k.date_added) FROM advisory_cves c JOIN kev_entries k ON k.cve = c.cve
    WHERE c.advisory_id = a.advisory_id) AS kev_date_added,
  (SELECT MAX(e.epss) FROM advisory_cves c JOIN epss_scores e ON e.cve = c.cve
    WHERE c.advisory_id = a.advisory_id) AS epss,
  (SELECT MAX(e.percentile) FROM advisory_cves c JOIN epss_scores e ON e.cve = c.cve
    WHERE c.advisory_id = a.advisory_id) AS epss_percentile
FROM advisories a
"""
_CLAIM_ADVISORIES = """
UNION ALL
SELECT advisory_id, kind, '[]', summary, NULL, NULL, NULL, first_seen_at, updated_at, withdrawn, 1,
  first_seen_at, updated_at, 0, NULL, NULL, NULL
FROM claim_advisories
"""
_AFFECTED = """
CREATE VIEW v_advisory_affected AS
SELECT r.advisory_id, f.record_id, f.ecosystem, f.name, f.purl, f.ranges_json, f.fixed_json,
  f.versions_json
FROM record_affected f JOIN osv_records r ON r.record_id = f.record_id
"""
_CLAIM_AFFECTED = """
UNION ALL
SELECT advisory_id, advisory_id, ecosystem, name, NULL, ranges_json, '[]', versions_json
FROM claim_advisories
"""
_REPORT_CLAIMS = """
CREATE VIEW v_report_claims AS
SELECT c.claim_id, c.report_id, c.ecosystem, c.package, c.versions_json, c.kind, c.quote, c.status,
  c.advisory_id, r.feed_id, r.trust, r.title, r.url, r.first_seen_at
FROM report_claims c JOIN reports r ON r.report_id = c.report_id
"""


def upgrade() -> None:
    op.add_column("report_claims", sa.Column("status", sa.Text, nullable=False, server_default="unconfirmed"))
    op.add_column("report_claims", sa.Column("status_reason", sa.Text))
    op.add_column("report_claims", sa.Column("linked_json", sa.Text, nullable=False, server_default="[]"))
    op.add_column("report_claims", sa.Column("advisory_id", sa.Text))
    op.add_column("report_claims", sa.Column("assessed_at", sa.Text))
    op.execute("UPDATE report_claims SET status = 'ungrounded' WHERE grounded = 0")
    op.create_index("ix_report_claims_status", "report_claims", ["status"])
    op.create_table(
        "claim_advisories",
        sa.Column("advisory_id", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),  # malicious / vulnerability
        sa.Column("ecosystem", sa.Text, nullable=False),  # OSV の表記
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("ranges_json", sa.Text, nullable=False),
        sa.Column("versions_json", sa.Text),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("claim_ids_json", sa.Text, nullable=False),
        sa.Column("withdrawn", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("withdrawn_reason", sa.Text),
        sa.Column("first_seen_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    for view in ("v_advisories", "v_advisory_affected"):
        op.execute(f"DROP VIEW IF EXISTS {view}")
    op.execute(_ADVISORIES + _CLAIM_ADVISORIES)
    op.execute(_AFFECTED + _CLAIM_AFFECTED)
    op.execute(_REPORT_CLAIMS)


def downgrade() -> None:
    for view in ("v_report_claims", "v_advisories", "v_advisory_affected"):
        op.execute(f"DROP VIEW IF EXISTS {view}")
    op.execute(_ADVISORIES)
    op.execute(_AFFECTED)
    op.drop_table("claim_advisories")
    op.drop_index("ix_report_claims_status", "report_claims")
    for col in ("assessed_at", "advisory_id", "linked_json", "status_reason", "status"):
        op.drop_column("report_claims", col)
