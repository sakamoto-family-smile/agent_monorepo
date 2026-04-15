"""Main analyzer - processes unanalyzed vulnerabilities from DB."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings
from ..db.migrations import init_db
from ..db.models import Vulnerability
from .inventory_match import match_vulnerability
from .llm_analyst import analyze_vulnerability
from .scorer import score_vulnerability

logger = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
ANALYZER_LOG = LOGS_DIR / "analyzer.jsonl"


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _jsonl_log(record: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(ANALYZER_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


async def _dispatch_notifications(
    session: AsyncSession,
    vulns: list[Vulnerability],
) -> None:
    """Send notifications for new critical/high vulnerabilities."""
    from ..notifier.formatter import format_immediate
    from ..notifier.slack import send_immediate as slack_send
    from ..notifier.line import send_message as line_send
    from ..notifier.email_notifier import send_email

    for vuln in vulns:
        if vuln.notification_sent:
            continue
        if vuln.severity not in ("CRITICAL", "HIGH"):
            continue

        try:
            text = format_immediate(vuln)
            subject = f"[{vuln.severity}] Security Alert: {vuln.title[:60]}"

            # Send to all configured channels
            await asyncio.gather(
                slack_send(text),
                line_send(text),
                send_email(subject, text, []),
                return_exceptions=True,
            )

            vuln.notification_sent = True
            vuln.notification_sent_at = datetime.now(tz=timezone.utc)

            _jsonl_log({
                "ts": datetime.now(tz=timezone.utc).isoformat(),
                "event": "notification_sent",
                "vuln_id": vuln.id,
                "severity": vuln.severity,
                "cve_id": vuln.cve_id,
            })
        except Exception as exc:
            logger.warning("Notification failed for vuln %s: %s", vuln.id, exc)


async def run_once() -> dict[str, int]:
    """Process all unanalyzed vulnerabilities.

    Returns counts of processed and notified vulnerabilities.
    """
    await init_db()
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    processed = 0
    notified = 0

    async with async_session() as session:
        # Fetch unanalyzed vulnerabilities (no inventory_match field analyzed yet)
        # We identify "unanalyzed" as those where matched_components is NULL
        result = await session.execute(
            select(Vulnerability).where(Vulnerability.matched_components.is_(None))
        )
        vulns: list[Vulnerability] = list(result.scalars().all())

        logger.info("Analyzer: found %d unanalyzed vulnerabilities", len(vulns))

        for vuln in vulns:
            try:
                # Build dict for analysis
                vuln_dict: dict[str, Any] = {
                    "source": vuln.source,
                    "cve_id": vuln.cve_id,
                    "ghsa_id": vuln.ghsa_id,
                    "title": vuln.title,
                    "description": vuln.description,
                    "severity": vuln.severity,
                    "cvss_score": vuln.cvss_score,
                    "cvss_vector": vuln.cvss_vector,
                    "affected_component_name": vuln.affected_component_name,
                    "affected_component_version": vuln.affected_component_version,
                    "affected_component_ecosystem": vuln.affected_component_ecosystem,
                    "tags": vuln.tags or [],
                    "owasp_asi": vuln.owasp_asi or [],
                }

                # Step 1: Inventory matching
                matched_components = match_vulnerability(vuln_dict)
                inventory_match = len(matched_components) > 0

                # Step 2: Score with inventory context
                scored = score_vulnerability(vuln_dict, inventory_match=inventory_match)

                # Step 3: Optional LLM analysis
                llm_result = await analyze_vulnerability(vuln_dict)

                # Update vulnerability in DB
                vuln.matched_components = matched_components
                vuln.inventory_match = inventory_match
                vuln.severity = scored.get("severity", vuln.severity)
                vuln.owasp_asi = scored.get("owasp_asi", vuln.owasp_asi)

                if llm_result:
                    vuln.attack_summary = llm_result.get("attack_summary")
                    vuln.applicability = llm_result.get("applicability")
                    vuln.recommended_actions = llm_result.get("recommended_actions")

                processed += 1

                _jsonl_log({
                    "ts": datetime.now(tz=timezone.utc).isoformat(),
                    "event": "vulnerability_analyzed",
                    "vuln_id": vuln.id,
                    "severity": vuln.severity,
                    "inventory_match": inventory_match,
                    "matched_components": matched_components,
                })

            except Exception as exc:
                logger.error("Analysis failed for vuln %s: %s", vuln.id, exc)

        await session.commit()

        # Dispatch notifications for newly analyzed critical/high vulns
        unnotified = [v for v in vulns if not v.notification_sent and v.severity in ("CRITICAL", "HIGH")]
        if unnotified:
            await _dispatch_notifications(session, unnotified)
            notified = len([v for v in unnotified if v.notification_sent])
            await session.commit()

    await engine.dispose()

    counts = {"processed": processed, "notified": notified}
    _jsonl_log({
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": "analysis_complete",
        "counts": counts,
    })

    logger.info("Analysis complete: processed=%d, notified=%d", processed, notified)
    return counts


async def run_scheduler() -> None:
    """Run analyzer on a schedule."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_once, "interval", hours=1, id="analyzer")
    scheduler.start()
    logger.info("Analyzer scheduler started (every hour)")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


def main() -> None:
    """CLI entry point."""
    _setup_logging()
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
