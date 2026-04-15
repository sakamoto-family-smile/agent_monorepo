"""Daily/weekly digest generator."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings
from ..db.migrations import init_db
from ..db.models import Vulnerability
from .email_notifier import send_email
from .formatter import format_digest
from .line import send_message as line_send
from .slack import send_digest as slack_send

logger = logging.getLogger(__name__)


async def _fetch_vulns_since(session: AsyncSession, since: datetime) -> list[Vulnerability]:
    """Fetch vulnerabilities ingested since a given datetime."""
    result = await session.execute(
        select(Vulnerability).where(Vulnerability.ingested_at >= since)
    )
    return list(result.scalars().all())


async def _send_digest_to_all_channels(subject: str, text: str) -> None:
    """Send a digest to all configured notification channels."""
    await asyncio.gather(
        slack_send(text),
        line_send(text),
        send_email(subject, text, []),
        return_exceptions=True,
    )


async def generate_daily_digest() -> str:
    """Generate and send the daily security digest.

    Covers vulnerabilities from the last 24 hours.
    Returns the digest text.
    """
    await init_db()
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)

    async with async_session() as session:
        vulns = await _fetch_vulns_since(session, since)

    await engine.dispose()

    digest_text = format_digest(vulns)
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    subject = f"[Security Digest] {now_str} - {len(vulns)} new vulnerabilities"

    await _send_digest_to_all_channels(subject, digest_text)
    logger.info("Daily digest sent: %d vulnerabilities", len(vulns))
    return digest_text


async def generate_weekly_digest() -> str:
    """Generate and send the weekly security digest.

    Covers vulnerabilities from the last 7 days.
    Returns the digest text.
    """
    await init_db()
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    since = datetime.now(tz=timezone.utc) - timedelta(days=7)

    async with async_session() as session:
        vulns = await _fetch_vulns_since(session, since)

    await engine.dispose()

    digest_text = format_digest(vulns)
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-W%W")
    subject = f"[Weekly Security Digest] {now_str} - {len(vulns)} vulnerabilities"

    await _send_digest_to_all_channels(subject, digest_text)
    logger.info("Weekly digest sent: %d vulnerabilities", len(vulns))
    return digest_text


def main() -> None:
    """CLI entry point - generate daily digest."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(generate_daily_digest())


if __name__ == "__main__":
    main()
