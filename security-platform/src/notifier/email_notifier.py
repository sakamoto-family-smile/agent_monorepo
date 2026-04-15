"""Email notifier using smtplib."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import partial
from typing import Sequence

from ..config import settings

logger = logging.getLogger(__name__)


def _send_email_sync(
    subject: str,
    body: str,
    to_addresses: list[str],
) -> bool:
    """Synchronous email sending via smtplib."""
    if not settings.smtp_user or not settings.smtp_password:
        logger.debug("SMTP not configured, skipping email")
        return False

    recipients = to_addresses or ([settings.notification_email] if settings.notification_email else [])
    if not recipients:
        logger.debug("No email recipients configured")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.sendmail(settings.smtp_user, recipients, msg.as_string())
        logger.info("Email sent to %s", recipients)
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP authentication failed: %s", exc)
        return False
    except smtplib.SMTPException as exc:
        logger.error("SMTP error: %s", exc)
        return False
    except Exception as exc:
        logger.error("Email sending failed: %s", exc)
        return False


async def send_email(
    subject: str,
    body: str,
    to_addresses: Sequence[str],
) -> bool:
    """Send an email asynchronously (runs smtplib in a thread executor).

    Returns True on success, False if not configured or on error.
    """
    if not settings.smtp_user or not settings.smtp_password:
        logger.debug("SMTP not configured, skipping email")
        return False

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_send_email_sync, subject, body, list(to_addresses)),
    )
