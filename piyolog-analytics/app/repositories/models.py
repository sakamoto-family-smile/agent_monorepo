"""SQLAlchemy declarative models。

旧 `repositories/schema.sql` の DDL を Python で表現したもの。
Alembic migration の autogenerate ターゲットとしても使う。
"""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """全モデル共通のベース。Alembic の MetaData ターゲットに使う。"""


class PiyologEvent(Base):
    __tablename__ = "piyolog_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    family_id: Mapped[str] = mapped_column(String, nullable=False)
    source_user_id: Mapped[str] = mapped_column(String, nullable=False)
    child_id: Mapped[str] = mapped_column(String, nullable=False, default="default")
    event_timestamp: Mapped[str] = mapped_column(String, nullable=False)  # ISO8601 +09:00
    event_date: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD JST
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    volume_ml: Mapped[float | None] = mapped_column(Float, nullable=True)
    left_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    right_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    head_circumference_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    import_batch_id: Mapped[str] = mapped_column(String, nullable=False)
    imported_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("idx_events_family_date", "family_id", "event_date"),
        Index("idx_events_family_type_date", "family_id", "event_type", "event_date"),
        Index("idx_events_batch", "import_batch_id"),
    )


class ImportBatchRow(Base):
    __tablename__ = "import_batches"

    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    family_id: Mapped[str] = mapped_column(String, nullable=False)
    source_user_id: Mapped[str] = mapped_column(String, nullable=False)
    source_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_hash: Mapped[str] = mapped_column(String, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_at: Mapped[str] = mapped_column(String, nullable=False)
    rolled_back_at: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_batches_family", "family_id", "imported_at"),
        # active な (rolled_back_at IS NULL) 単位での重複検知用 partial unique index。
        # SQLite / Postgres ともに `WHERE rolled_back_at IS NULL` 構文をサポート。
        Index(
            "idx_batches_hash_dedup",
            "family_id",
            "raw_text_hash",
            unique=True,
            sqlite_where=text("rolled_back_at IS NULL"),
            postgresql_where=text("rolled_back_at IS NULL"),
        ),
    )
