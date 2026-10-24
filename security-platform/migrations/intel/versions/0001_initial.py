"""intel.db 初期スキーマ (A1 情報取得)

Revision ID: 0001
Revises:
Create Date: 2026-10-24

テーブルの役割:
  osv_records / record_aliases / record_affected  OSV レコード (情報源の事実をそのまま)
  kev_entries / epss_scores                       KEV・EPSS (CVE 単位)
  advisories / advisory_cves                      レコードを CVE 等で名寄せした Advisory
  advisory_history                                Advisory の変化の履歴
  advisories_dirty                                再集計待ち (レコード書き込みと同じトランザクションで積む)
  source_cursors / source_runs / meta             取得位置・実行記録・ブートストラップ状態
  events                                          outbox (advisory.changed 等)
ビュー v_advisories / v_advisory_affected / v_advisory_aliases は A2・B への読み取り契約。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

V_ADVISORIES = """
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

V_ADVISORY_AFFECTED = """
CREATE VIEW v_advisory_affected AS
SELECT r.advisory_id, f.record_id, f.ecosystem, f.name, f.purl, f.ranges_json, f.fixed_json
FROM record_affected f JOIN osv_records r ON r.record_id = f.record_id
"""

V_ADVISORY_ALIASES = """
CREATE VIEW v_advisory_aliases AS
SELECT DISTINCT r.advisory_id, x.alias, x.relation
FROM record_aliases x JOIN osv_records r ON r.record_id = x.record_id
"""


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.Text, nullable=nullable)  # ISO8601 (UTC)


def upgrade() -> None:
    op.create_table(
        "osv_records",
        sa.Column("record_id", sa.Text, primary_key=True),
        sa.Column("advisory_id", sa.Text, nullable=False, index=True),
        sa.Column("db_prefix", sa.Text, nullable=False),  # GHSA / PYSEC / DSA / CVE ...
        sa.Column("summary", sa.Text),
        sa.Column("cvss_vector", sa.Text),
        sa.Column("cvss_score", sa.Float),
        sa.Column("severity_label", sa.Text),
        sa.Column("withdrawn", sa.Boolean, nullable=False, server_default=sa.false()),
        _ts("published_at"),
        _ts("modified_at"),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("raw_ref", sa.Text, nullable=False),
        _ts("ingested_at", nullable=False),
        _ts("updated_at", nullable=False),
    )
    op.create_table(
        "record_aliases",
        sa.Column("record_id", sa.Text, primary_key=True),
        sa.Column("alias", sa.Text, primary_key=True),
        sa.Column("relation", sa.Text, nullable=False),  # alias / upstream
    )
    op.create_index("ix_record_aliases_alias", "record_aliases", ["alias"])
    op.create_table(
        "record_affected",
        sa.Column("record_id", sa.Text, primary_key=True),
        sa.Column("idx", sa.Integer, primary_key=True),
        sa.Column("ecosystem", sa.Text),
        sa.Column("name", sa.Text),
        sa.Column("purl", sa.Text),
        sa.Column("ranges_json", sa.Text, nullable=False),
        sa.Column("fixed_json", sa.Text, nullable=False),
        sa.Column("versions_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_record_affected_pkg", "record_affected", ["ecosystem", "name"])
    op.create_table(
        "kev_entries",
        sa.Column("cve", sa.Text, primary_key=True),
        sa.Column("vendor", sa.Text),
        sa.Column("product", sa.Text),
        sa.Column("name", sa.Text),
        sa.Column("date_added", sa.Text),
        sa.Column("due_date", sa.Text),
        sa.Column("ransomware", sa.Text),
        sa.Column("short_description", sa.Text),
        sa.Column("raw_ref", sa.Text, nullable=False),
        _ts("updated_at", nullable=False),
    )
    op.create_table(
        "epss_scores",
        sa.Column("cve", sa.Text, primary_key=True),
        sa.Column("epss", sa.Float, nullable=False),
        sa.Column("percentile", sa.Float, nullable=False),
        sa.Column("score_date", sa.Text),
        _ts("updated_at", nullable=False),
    )
    op.create_table(
        "advisories",
        sa.Column("advisory_id", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False, server_default="vulnerability"),
        sa.Column("cves_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text),
        sa.Column("cvss_score", sa.Float),
        sa.Column("cvss_vector", sa.Text),
        sa.Column("severity", sa.Text),
        _ts("published_at"),
        _ts("modified_at"),
        sa.Column("withdrawn", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("record_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("affected_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("fixed_hash", sa.Text, nullable=False, server_default=""),
        _ts("first_seen_at", nullable=False),
        _ts("updated_at", nullable=False),
    )
    op.create_table(
        "advisory_cves",
        sa.Column("advisory_id", sa.Text, primary_key=True),
        sa.Column("cve", sa.Text, primary_key=True),
    )
    op.create_index("ix_advisory_cves_cve", "advisory_cves", ["cve"])
    op.create_table(
        "advisories_dirty",
        sa.Column("advisory_id", sa.Text, primary_key=True),
    )
    op.create_table(
        "advisory_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("advisory_id", sa.Text, nullable=False, index=True),
        sa.Column("change_types_json", sa.Text, nullable=False),
        sa.Column("previous_json", sa.Text, nullable=False),
        sa.Column("current_json", sa.Text, nullable=False),
        sa.Column("run_id", sa.Text, nullable=False),
        _ts("occurred_at", nullable=False),
    )
    op.create_table(
        "source_cursors",
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("cursor", sa.Text, nullable=False),
        _ts("updated_at", nullable=False),
    )
    op.create_table(
        "source_runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("mode", sa.Text, nullable=False),
        _ts("started_at", nullable=False),
        _ts("finished_at"),
        sa.Column("status", sa.Text, nullable=False),  # running / success / failed
        sa.Column("fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("changed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_source_runs_source", "source_runs", ["source", "started_at"])
    op.create_table(
        "meta",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("seq", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Text, nullable=False, unique=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        _ts("occurred_at", nullable=False),
    )
    op.execute(V_ADVISORIES)
    op.execute(V_ADVISORY_AFFECTED)
    op.execute(V_ADVISORY_ALIASES)


def downgrade() -> None:
    for view in ("v_advisory_aliases", "v_advisory_affected", "v_advisories"):
        op.execute(f"DROP VIEW IF EXISTS {view}")
    for table in (
        "events", "meta", "source_runs", "source_cursors", "advisory_history",
        "advisories_dirty", "advisory_cves", "advisories", "epss_scores", "kev_entries",
        "record_affected", "record_aliases", "osv_records",
    ):
        op.drop_table(table)
