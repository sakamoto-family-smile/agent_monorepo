"""Slack Webhook notifier."""
from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


async def send_immediate(text: str) -> bool:
    """Send an immediate alert to Slack.

    Returns True on success, False if not configured or on error.
    """
    if not settings.slack_webhook_url:
        logger.debug("Slack webhook not configured, skipping")
        return False

    return await _post(text)


async def send_digest(text: str) -> bool:
    """Send a digest message to Slack.

    Returns True on success, False if not configured or on error.
    """
    if not settings.slack_webhook_url:
        logger.debug("Slack webhook not configured, skipping")
        return False

    return await _post(text)


async def _post(text: str) -> bool:
    """Post a message to the Slack webhook."""
    payload = {"text": text}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(settings.slack_webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Slack notification sent")
            return True
    except httpx.HTTPStatusError as exc:
        logger.error("Slack HTTP error: %s %s", exc.response.status_code, exc.response.text)
        return False
    except Exception as exc:
        logger.error("Slack notification failed: %s", exc)
        return False
