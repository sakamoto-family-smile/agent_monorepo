"""Tests for database models using async SQLAlchemy."""
from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import AuditLog, Base, Vulnerability


async def _make_session_factory(tmp_path):
    """Set up an in-memory SQLite DB and return a session factory."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory


@pytest.mark.anyio
async def test_create_vulnerability(tmp_path):
    """Insert a Vulnerability, read it back, verify fields."""
    factory = await _make_session_factory(tmp_path)
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    async with factory() as session:
        vuln = Vulnerability(
            source="nvd",
            cve_id="CVE-2024-1234",
            title="Test Vulnerability",
            description="A test vulnerability for unit tests.",
            severity="HIGH",
            cvss_score=8.5,
            inventory_match=False,
        )
        session.add(vuln)
        await session.commit()
        vuln_id = vuln.id

    async with factory() as session:
        result = await session.execute(
            select(Vulnerability).where(Vulnerability.id == vuln_id)
        )
        fetched = result.scalar_one()
        assert fetched.cve_id == "CVE-2024-1234"
        assert fetched.severity == "HIGH"
        assert fetched.cvss_score == 8.5
        assert fetched.source == "nvd"
        assert fetched.title == "Test Vulnerability"


@pytest.mark.anyio
async def test_create_audit_log(tmp_path):
    """Insert an AuditLog entry, read it back, verify fields."""
    factory = await _make_session_factory(tmp_path)
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    async with factory() as session:
        entry = AuditLog(
            event_type="tool_call",
            tool_name="web_search",
            parameters_summary='{"query": "python tutorials"}',
            result_summary="HTTP 200",
            client_id="test-client",
            created_at=now,
            flagged=False,
        )
        session.add(entry)
        await session.commit()
        entry_id = entry.id

    async with factory() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.id == entry_id)
        )
        fetched = result.scalar_one()
        assert fetched.event_type == "tool_call"
        assert fetched.tool_name == "web_search"
        assert fetched.flagged is False
        assert fetched.client_id == "test-client"


@pytest.mark.anyio
async def test_vulnerability_dedup_by_cve_id(tmp_path):
    """Inserting two vulnerabilities with different CVE IDs should work fine.
    Both should exist as separate rows (SQLite has no unique constraint on cve_id by default).
    """
    factory = await _make_session_factory(tmp_path)

    async with factory() as session:
        v1 = Vulnerability(
            source="nvd",
            cve_id="CVE-2024-0001",
            title="First Vuln",
            severity="LOW",
        )
        v2 = Vulnerability(
            source="nvd",
            cve_id="CVE-2024-0002",
            title="Second Vuln",
            severity="HIGH",
        )
        session.add_all([v1, v2])
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(Vulnerability))
        rows = result.scalars().all()
        cve_ids = {r.cve_id for r in rows}
        assert "CVE-2024-0001" in cve_ids
        assert "CVE-2024-0002" in cve_ids


@pytest.mark.anyio
async def test_audit_log_flagged_entry(tmp_path):
    """Flagged audit log entries should store the flag reason."""
    factory = await _make_session_factory(tmp_path)
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    async with factory() as session:
        entry = AuditLog(
            event_type="inbound_blocked_injection",
            tool_name="exec_tool",
            parameters_summary='{"cmd": "; rm -rf /"}',
            result_summary="BLOCKED: Injection detected",
            client_id="attacker",
            created_at=now,
            flagged=True,
            flag_reason="INJECTION: Command injection detected at root.cmd",
        )
        session.add(entry)
        await session.commit()
        entry_id = entry.id

    async with factory() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.id == entry_id)
        )
        fetched = result.scalar_one()
        assert fetched.flagged is True
        assert "INJECTION" in fetched.flag_reason
