"""FastAPI dashboard application."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings
from ..db.migrations import init_db
from ..db.models import AuditLog, Component, ScanResult, Vulnerability

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(
    title="Agent Security Platform",
    description="Security monitoring dashboard for AI agent systems",
    version="0.1.0",
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _make_engine():
    return create_async_engine(settings.database_url, echo=False)


def _make_session(engine):
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    logger.info("Dashboard started on %s:%s", settings.dashboard_host, settings.dashboard_port)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main dashboard HTML page."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/vulnerabilities")
async def get_vulnerabilities(
    severity: str | None = Query(default=None, description="Filter by severity (CRITICAL/HIGH/MEDIUM/LOW)"),
    days: int = Query(default=30, description="Look back N days"),
    affected_only: bool = Query(default=False, description="Only show inventory-matched vulnerabilities"),
    limit: int = Query(default=100, description="Maximum results"),
    offset: int = Query(default=0, description="Pagination offset"),
) -> dict[str, Any]:
    """List vulnerabilities with optional filters."""
    engine = _make_engine()
    async_session = _make_session(engine)

    since = datetime.now(tz=timezone.utc) - timedelta(days=days)

    async with async_session() as session:
        query = select(Vulnerability).where(Vulnerability.ingested_at >= since)

        if severity:
            query = query.where(Vulnerability.severity == severity.upper())
        if affected_only:
            query = query.where(Vulnerability.inventory_match == True)

        query = query.order_by(desc(Vulnerability.ingested_at)).offset(offset).limit(limit)

        result = await session.execute(query)
        vulns = result.scalars().all()

        # Total count
        count_query = select(func.count(Vulnerability.id)).where(Vulnerability.ingested_at >= since)
        if severity:
            count_query = count_query.where(Vulnerability.severity == severity.upper())
        if affected_only:
            count_query = count_query.where(Vulnerability.inventory_match == True)
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

    await engine.dispose()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "vulnerabilities": [
            {
                "id": v.id,
                "source": v.source,
                "cve_id": v.cve_id,
                "ghsa_id": v.ghsa_id,
                "title": v.title,
                "severity": v.severity,
                "cvss_score": v.cvss_score,
                "affected_component": v.affected_component_name,
                "affected_version": v.affected_component_version,
                "inventory_match": v.inventory_match,
                "matched_components": v.matched_components,
                "owasp_asi": v.owasp_asi,
                "published_at": v.published_at.isoformat() if v.published_at else None,
                "ingested_at": v.ingested_at.isoformat() if v.ingested_at else None,
                "notification_sent": v.notification_sent,
                "attack_summary": v.attack_summary,
                "recommended_actions": v.recommended_actions,
            }
            for v in vulns
        ],
    }


@app.get("/api/stats")
async def get_stats() -> dict[str, Any]:
    """Return summary statistics for the dashboard."""
    engine = _make_engine()
    async_session = _make_session(engine)

    last_7_days = datetime.now(tz=timezone.utc) - timedelta(days=7)
    last_30_days = datetime.now(tz=timezone.utc) - timedelta(days=30)

    async with async_session() as session:
        # Unresolved critical (not notified)
        crit_result = await session.execute(
            select(func.count(Vulnerability.id)).where(
                Vulnerability.severity == "CRITICAL",
                Vulnerability.notification_sent == False,
            )
        )
        critical_unresolved = crit_result.scalar() or 0

        # Unresolved high
        high_result = await session.execute(
            select(func.count(Vulnerability.id)).where(
                Vulnerability.severity == "HIGH",
                Vulnerability.notification_sent == False,
            )
        )
        high_unresolved = high_result.scalar() or 0

        # New in last 7 days
        new_result = await session.execute(
            select(func.count(Vulnerability.id)).where(
                Vulnerability.ingested_at >= last_7_days
            )
        )
        new_7_days = new_result.scalar() or 0

        # Systems affected (with inventory match)
        affected_result = await session.execute(
            select(func.count(Vulnerability.id)).where(
                Vulnerability.inventory_match == True,
                Vulnerability.ingested_at >= last_30_days,
            )
        )
        systems_affected = affected_result.scalar() or 0

        # Severity breakdown (last 30 days)
        severity_counts: dict[str, int] = {}
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            count_result = await session.execute(
                select(func.count(Vulnerability.id)).where(
                    Vulnerability.severity == sev,
                    Vulnerability.ingested_at >= last_30_days,
                )
            )
            severity_counts[sev] = count_result.scalar() or 0

        # Source breakdown
        sources_result = await session.execute(
            select(Vulnerability.source, func.count(Vulnerability.id))
            .where(Vulnerability.ingested_at >= last_30_days)
            .group_by(Vulnerability.source)
        )
        source_counts = {row[0]: row[1] for row in sources_result}

    await engine.dispose()

    return {
        "critical_unresolved": critical_unresolved,
        "high_unresolved": high_unresolved,
        "new_7_days": new_7_days,
        "systems_affected": systems_affected,
        "severity_breakdown": severity_counts,
        "source_breakdown": source_counts,
    }


@app.get("/api/inventory")
async def get_inventory() -> dict[str, Any]:
    """Return the component inventory status."""
    engine = _make_engine()
    async_session = _make_session(engine)

    async with async_session() as session:
        result = await session.execute(
            select(Component).where(Component.active == True)
        )
        components = result.scalars().all()

        # Count vulnerabilities per component name
        vuln_counts: dict[str, int] = {}
        for comp in components:
            count_result = await session.execute(
                select(func.count(Vulnerability.id)).where(
                    Vulnerability.affected_component_name == comp.name
                )
            )
            vuln_counts[comp.name] = count_result.scalar() or 0

    await engine.dispose()

    return {
        "components": [
            {
                "id": c.id,
                "name": c.name,
                "version": c.version,
                "ecosystem": c.ecosystem,
                "component_type": c.component_type,
                "config_path": c.config_path,
                "active": c.active,
                "vulnerability_count": vuln_counts.get(c.name, 0),
                "last_updated": c.last_updated.isoformat() if c.last_updated else None,
            }
            for c in components
        ]
    }


@app.get("/api/audit-log")
async def get_audit_log(limit: int = Query(default=50)) -> dict[str, Any]:
    """Return recent proxy audit log entries."""
    engine = _make_engine()
    async_session = _make_session(engine)

    async with async_session() as session:
        result = await session.execute(
            select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
        )
        entries = result.scalars().all()

    await engine.dispose()

    return {
        "entries": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "tool_name": e.tool_name,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "flagged": e.flagged,
                "flag_reason": e.flag_reason,
                "client_id": e.client_id,
            }
            for e in entries
        ]
    }


@app.post("/api/collect")
async def trigger_collect() -> dict[str, Any]:
    """Trigger a manual vulnerability collection run."""
    from ..collector.main import run_once
    try:
        counts = await run_once()
        return {"status": "success", "counts": counts}
    except Exception as exc:
        logger.error("Manual collection failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/analyze")
async def trigger_analyze() -> dict[str, Any]:
    """Trigger a manual analysis run."""
    from ..analyzer.main import run_once
    try:
        counts = await run_once()
        return {"status": "success", "counts": counts}
    except Exception as exc:
        logger.error("Manual analysis failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/digest")
async def trigger_digest() -> dict[str, Any]:
    """Trigger a manual daily digest."""
    from ..notifier.digest import generate_daily_digest
    try:
        text = await generate_daily_digest()
        return {"status": "success", "digest_length": len(text)}
    except Exception as exc:
        logger.error("Manual digest failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def main() -> None:
    """CLI entry point to run the dashboard server."""
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.dashboard_host, port=settings.dashboard_port)


if __name__ == "__main__":
    main()
