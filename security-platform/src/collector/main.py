"""Main collector orchestrator - runs all collectors and saves to DB."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings
from ..db.migrations import init_db
from ..db.models import Component, Vulnerability
from .github_advisory import GitHubAdvisoryCollector
from .nvd import NVDCollector
from .osv import OSVCollector
from .vulnerable_mcp import VulnerableMCPCollector

logger = logging.getLogger(__name__)

# Path to log file
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
COLLECTOR_LOG = LOGS_DIR / "collector.jsonl"


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _jsonl_log(record: dict[str, Any]) -> None:
    """Append a JSON Lines record to the collector log."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(COLLECTOR_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert datetime objects to ISO strings for JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _load_inventory_packages() -> list[dict[str, str]]:
    """Load packages from inventory.yaml for OSV batch querying."""
    import yaml
    inventory_path = Path(__file__).parent.parent.parent / "config" / "inventory.yaml"
    if not inventory_path.exists():
        return []
    with open(inventory_path) as f:
        data = yaml.safe_load(f)
    packages = []
    for pkg in data.get("npm_packages", []):
        packages.append({"name": pkg["name"], "ecosystem": "npm"})
    for pkg in data.get("python_packages", []):
        packages.append({"name": pkg["name"], "ecosystem": "PyPI"})
    return packages


def _load_scan_keywords() -> list[str]:
    """Load NVD keywords from scan.yaml."""
    import yaml
    scan_path = Path(__file__).parent.parent.parent / "config" / "scan.yaml"
    if not scan_path.exists():
        return ["mcp", "model context protocol", "claude", "agent", "llm", "prompt injection"]
    with open(scan_path) as f:
        data = yaml.safe_load(f)
    return data.get("collector", {}).get("nvd", {}).get("keywords", [])


async def _upsert_vulnerability(session: AsyncSession, vuln: dict[str, Any]) -> bool:
    """Insert a vulnerability if it doesn't already exist. Returns True if new."""
    # Check by CVE ID or GHSA ID
    existing = None
    cve_id = vuln.get("cve_id")
    ghsa_id = vuln.get("ghsa_id")

    if cve_id:
        result = await session.execute(
            select(Vulnerability).where(Vulnerability.cve_id == cve_id)
        )
        existing = result.scalar_one_or_none()

    if not existing and ghsa_id:
        result = await session.execute(
            select(Vulnerability).where(Vulnerability.ghsa_id == ghsa_id)
        )
        existing = result.scalar_one_or_none()

    if existing:
        return False

    # Check for source-specific deduplication by title
    if not cve_id and not ghsa_id:
        result = await session.execute(
            select(Vulnerability).where(
                Vulnerability.source == vuln.get("source", ""),
                Vulnerability.title == vuln.get("title", ""),
            )
        )
        if result.scalar_one_or_none():
            return False

    obj = Vulnerability(
        source=vuln.get("source", "unknown"),
        cve_id=vuln.get("cve_id"),
        ghsa_id=vuln.get("ghsa_id"),
        title=vuln.get("title", ""),
        description=vuln.get("description", ""),
        severity=vuln.get("severity", "LOW"),
        cvss_score=vuln.get("cvss_score"),
        cvss_vector=vuln.get("cvss_vector"),
        affected_component_name=vuln.get("affected_component_name"),
        affected_component_version=vuln.get("affected_component_version"),
        affected_component_ecosystem=vuln.get("affected_component_ecosystem"),
        tags=vuln.get("tags", []),
        owasp_asi=vuln.get("owasp_asi", []),
        published_at=vuln.get("published_at"),
        ingested_at=datetime.now(tz=timezone.utc),
        notification_sent=False,
        raw_data=_sanitize_for_json(vuln.get("raw_data")),
    )
    session.add(obj)
    return True


async def _sync_inventory(session: AsyncSession) -> None:
    """Sync inventory.yaml components to the DB."""
    import yaml
    inventory_path = Path(__file__).parent.parent.parent / "config" / "inventory.yaml"
    if not inventory_path.exists():
        return
    with open(inventory_path) as f:
        data = yaml.safe_load(f)

    now = datetime.now(tz=timezone.utc)

    async def upsert_component(name: str, version: str, ecosystem: str, component_type: str, config_path: str = "") -> None:
        result = await session.execute(
            select(Component).where(Component.name == name, Component.component_type == component_type)
        )
        comp = result.scalar_one_or_none()
        if comp is None:
            comp = Component(
                name=name,
                version=version,
                ecosystem=ecosystem,
                component_type=component_type,
                config_path=config_path,
                active=True,
                last_updated=now,
            )
            session.add(comp)
        else:
            comp.version = version
            comp.active = True
            comp.last_updated = now

    for item in data.get("mcp_servers", []):
        await upsert_component(
            item["name"], item.get("version", "latest"), "npm", "mcp_server", item.get("config_path", "")
        )
    for item in data.get("skills", []):
        await upsert_component(item["name"], "latest", "skill", "skill", item.get("path", ""))
    for item in data.get("npm_packages", []):
        await upsert_component(item["name"], item.get("version", "latest"), "npm", "npm_package")
    for item in data.get("python_packages", []):
        await upsert_component(item["name"], item.get("version", "latest"), "PyPI", "python_package")


async def run_once() -> dict[str, int]:
    """Run all collectors once and save results to DB.

    Returns a dict with counts per source.
    """
    await init_db()
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    keywords = _load_scan_keywords()
    packages = _load_inventory_packages()

    counts: dict[str, int] = {}

    # Run collectors concurrently
    logger.info("Starting all collectors...")
    nvd = NVDCollector()
    gh = GitHubAdvisoryCollector()
    osv = OSVCollector()
    vmcp = VulnerableMCPCollector()

    results = await asyncio.gather(
        nvd.fetch_recent(keywords, days_back=7),
        gh.fetch_recent(["npm", "pip", "go"], days_back=7),
        osv.fetch_batch(packages),
        vmcp.fetch_all(),
        return_exceptions=True,
    )

    source_names = ["nvd", "github_advisory", "osv", "vulnerable_mcp"]
    all_vulns: list[dict[str, Any]] = []

    for name, result in zip(source_names, results):
        if isinstance(result, Exception):
            logger.error("Collector %s failed: %s", name, result)
            counts[name] = 0
            _jsonl_log({"ts": datetime.now(tz=timezone.utc).isoformat(), "event": "collector_error", "source": name, "error": str(result)})
        else:
            counts[name] = len(result)
            all_vulns.extend(result)
            logger.info("Collector %s: %d findings", name, len(result))

    # Save to DB
    new_count = 0
    async with async_session() as session:
        await _sync_inventory(session)
        for vuln in all_vulns:
            is_new = await _upsert_vulnerability(session, vuln)
            if is_new:
                new_count += 1
        await session.commit()

    await engine.dispose()
    counts["new_total"] = new_count

    _jsonl_log({
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": "collection_complete",
        "counts": counts,
    })

    logger.info("Collection complete. New vulnerabilities: %d", new_count)
    return counts


async def run_scheduler() -> None:
    """Run the collector on a schedule using APScheduler."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_once, "interval", hours=2, id="collector")
    scheduler.start()
    logger.info("Collector scheduler started (every 2 hours)")

    try:
        # Keep running
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


def main() -> None:
    """CLI entry point - run collector once."""
    _setup_logging()
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
