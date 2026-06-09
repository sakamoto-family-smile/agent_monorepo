"""SQLAlchemy declarative models (PROPOSAL-0011 P2-B)。

旧 `database.py` の SQLite DDL を Python で表現し、dev=SQLite / prod=Postgres を
1 コードで扱う。Alembic autogenerate のターゲットも本 Base.metadata。

スコープ: core 4 テーブル (ticker_dictionary / price_cache / reports / alerts) +
edinet_documents (PROPOSAL-0011 P3-B で shared Cloud SQL へ移行)。
"""

from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """全モデル共通のベース。Alembic の MetaData ターゲット。"""


# CURRENT_TIMESTAMP は SQLite / Postgres 双方で有効 (文字列 ISO 風)。
_NOW = text("CURRENT_TIMESTAMP")


class TickerDictionary(Base):
    __tablename__ = "ticker_dictionary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'[]'"))
    market: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'unknown'")
    )
    created_at: Mapped[str] = mapped_column(String, server_default=_NOW)
    updated_at: Mapped[str] = mapped_column(String, server_default=_NOW)

    __table_args__ = (UniqueConstraint("company_name", "ticker", name="uq_ticker_dict"),)


class PriceCache(Base):
    __tablename__ = "price_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False)
    cached_at: Mapped[str] = mapped_column(String, server_default=_NOW)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (UniqueConstraint("ticker", "period", name="uq_price_cache"),)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String, nullable=True)
    report_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, server_default=_NOW)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    alert_type: Mapped[str] = mapped_column(String, nullable=False)
    condition_data: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[str] = mapped_column(String, server_default=_NOW)


class EdinetDocument(Base):
    """EDINET 文書 INDEX (proposal 0006 Phase 1e / 0011 P3-B で Cloud SQL 化)。

    日付系 (submit_date / period_end / *_at) は ISO 文字列 (TEXT) で保持し、
    repo 側で date/datetime に変換する (旧 SQLite 実装との互換)。
    """

    __tablename__ = "edinet_documents"

    document_id: Mapped[str] = mapped_column(String, primary_key=True)
    edinet_code: Mapped[str] = mapped_column(String, nullable=False)
    securities_code: Mapped[str | None] = mapped_column(String, nullable=True)
    submitter_name: Mapped[str] = mapped_column(String, nullable=False)
    document_type: Mapped[str] = mapped_column(String, nullable=False)
    submit_date: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD
    period_end: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    withdrawal_status: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    disclosure_status: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    doc_info_edit_status: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    xbrl_flag: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    pdf_flag: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    attach_doc_flag: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cache_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    cached_at: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen_at: Mapped[str] = mapped_column(String, nullable=False, server_default=_NOW)
    last_index_refreshed_at: Mapped[str] = mapped_column(
        String, nullable=False, server_default=_NOW
    )

    __table_args__ = (
        Index("idx_edinet_docs_sec_code_date", "securities_code", "submit_date"),
        Index("idx_edinet_docs_edinet_code_date", "edinet_code", "submit_date"),
        Index("idx_edinet_docs_type_date", "document_type", "submit_date"),
    )


__all__ = [
    "Base",
    "TickerDictionary",
    "PriceCache",
    "Report",
    "Alert",
    "EdinetDocument",
]
