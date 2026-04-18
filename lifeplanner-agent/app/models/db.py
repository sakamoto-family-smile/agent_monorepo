"""
SQLAlchemy ORM モデル。

Phase 1 は Household と Transaction の 2 テーブルのみ。
金額は Numeric(14, 0) で円単位 Integer 相当に保持する（float を避ける）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Date,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Household(Base):
    __tablename__ = "households"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("household_id", "source_id", name="uq_transactions_household_source"),
        Index("ix_transactions_household_date", "household_id", "date"),
        Index("ix_transactions_household_category", "household_id", "category"),
        Index("ix_transactions_household_canonical", "household_id", "canonical_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # MF の ID（同一家計内で一意）
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    account: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 自社 canonical カテゴリ (MF 大項目 → mf_to_canonical.yaml で変換)
    canonical_category: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    # 固定費/変動費/収入 の区分 (fixed/variable/income)
    expense_type: Mapped[str] = mapped_column(String(16), nullable=False, default="variable")
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_target: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    household: Mapped[Household] = relationship(back_populates="transactions", lazy="noload")


class HouseholdMember(Base):
    """世帯メンバー (F2)。配偶者・子供・扶養家族を管理。"""

    __tablename__ = "household_members"
    __table_args__ = (
        Index("ix_members_household", "household_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # owner / spouse / child / dependent
    relation: Mapped[str] = mapped_column(String(32), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 雇用形態: employed / self_employed / student / retired / none
    employment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    annual_income: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Asset(Base):
    """資産 (F2)。現預金・投資・不動産など。"""

    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_household", "household_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    # cash / deposit / investment / real_estate / other
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(16, 0), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Liability(Base):
    """負債 (F2)。住宅ローン・車ローン・その他。"""

    __tablename__ = "liabilities"
    __table_args__ = (
        Index("ix_liabilities_household", "household_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    # mortgage / car_loan / credit_card / student_loan / other
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(16, 0), nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=0)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Scenario(Base):
    """ライフプランシナリオ。ベース前提と複数イベントの集合を保持する。"""

    __tablename__ = "scenarios"
    __table_args__ = (
        Index("ix_scenarios_household", "household_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # HouseholdProfile + SimulationAssumptions を JSON に保持(Phase 2 用の簡易実装)
    base_assumptions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    events: Mapped[list["LifeEvent"]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    results: Mapped[list["SimulationResultRow"]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class LifeEvent(Base):
    """シナリオに紐づくライフイベント。event_type と params_json で可変パラメータを保持。"""

    __tablename__ = "life_events"
    __table_args__ = (
        Index("ix_life_events_scenario", "scenario_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "E01" 等
    start_year: Mapped[int] = mapped_column(Integer, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scenario: Mapped[Scenario] = relationship(back_populates="events", lazy="noload")


class SimulationResultRow(Base):
    """シミュレーション実行結果(年次)。"""

    __tablename__ = "simulation_results"
    __table_args__ = (
        Index("ix_simulation_results_scenario_year", "scenario_id", "year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scenario: Mapped[Scenario] = relationship(back_populates="results", lazy="noload")
