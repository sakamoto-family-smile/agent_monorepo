"""LINE Notify notifier."""
from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

LINE_NOTIFY_API = "https://notify-api.line.me/api/notify"


async def send_message(text: str) -> bool:
    """Send a message via LINE Notify.

    Returns True on success, False if not configured or on error.
    """
    if not settings.line_notify_token:
        logger.debug("LINE Notify token not configured, skipping")
        return False

    headers = {
        "Authorization": f"Bearer {settings.line_notify_token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # LINE Notify has a 1000 char limit per message
    truncated = text[:990] + "..." if len(text) > 990 else text

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                LINE_NOTIFY_API,
                headers=headers,
                data={"message": truncated},
            )
            resp.raise_for_status()
            logger.info("LINE Notify message sent")
            return True
    except httpx.HTTPStatusError as exc:
        logger.error("LINE Notify HTTP error: %s %s", exc.response.status_code, exc.response.text)
        return False
    except Exception as exc:
        logger.error("LINE Notify failed: %s", exc)
        return False
