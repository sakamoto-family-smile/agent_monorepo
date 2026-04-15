"""SQLAlchemy ORM models for the security platform."""
from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class Vulnerability(Base):
    """Represents a security vulnerability ingested from external sources."""

    __tablename__ = "vulnerabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Source identifiers
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cve_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    ghsa_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # Core fields
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # CRITICAL/HIGH/MEDIUM/LOW
    cvss_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cvss_vector: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Affected component
    affected_component_name: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    affected_component_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    affected_component_ecosystem: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Metadata
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    owasp_asi: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    ingested_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )

    # Analysis results
    inventory_match: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    matched_components: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    attack_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    applicability: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_actions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Notification state
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notification_sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    # Raw data
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<Vulnerability id={self.id} cve={self.cve_id} severity={self.severity}>"


class Component(Base):
    """Represents a tracked component from the inventory."""

    __tablename__ = "components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ecosystem: Mapped[str | None] = mapped_column(String(32), nullable=True)
    config_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    component_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # mcp_server / skill / npm_package / python_package
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<Component name={self.name} type={self.component_type}>"


class ScanResult(Base):
    """Stores results from security scans (Snyk, gitleaks, etc.)."""

    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_type: Mapped[str] = mapped_column(String(64), nullable=False)  # mcp / skills / gitleaks / redteam
    target_path: Mapped[str] = mapped_column(String(512), nullable=False)
    scanner: Mapped[str] = mapped_column(String(64), nullable=False)
    findings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    severity_summary: Mapped[dict[str, int] | None] = mapped_column(JSON, nullable=True)
    ran_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")  # completed / failed

    def __repr__(self) -> str:
        return f"<ScanResult type={self.scan_type} target={self.target_path} status={self.status}>"


class AuditLog(Base):
    """Proxy audit log entry for MCP tool calls."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    tool_name: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    tool_description_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parameters_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow, index=True
    )
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flag_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} tool={self.tool_name} flagged={self.flagged}>"


class ToolPin(Base):
    """Stores tool description hashes for integrity verification (anti-rug-pull)."""

    __tablename__ = "tool_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    server_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
    last_verified: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<ToolPin tool={self.tool_name} hash={self.description_hash[:8]}...>"
