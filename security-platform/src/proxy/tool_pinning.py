"""Tool definition integrity verification - detect Rug Pull attacks."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings
from ..db.models import ToolPin

logger = logging.getLogger(__name__)


def _compute_hash(description: str) -> str:
    """Compute a SHA-256 hash of a tool description."""
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


class ToolPinStore:
    """Stores and verifies tool description integrity hashes.

    Detects "rug pull" attacks where MCP server operators change tool
    descriptions after the agent has established trust.
    """

    def __init__(self) -> None:
        self._engine = create_async_engine(settings.database_url, echo=False)
        self._async_session = sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def register(
        self,
        tool_name: str,
        description: str,
        server_name: str | None = None,
    ) -> str:
        """Register a tool's description hash.

        If the tool is already registered, this is a no-op (first-seen wins).
        Returns the description hash.
        """
        description_hash = _compute_hash(description)
        now = datetime.now(tz=timezone.utc)

        async with self._async_session() as session:
            result = await session.execute(
                select(ToolPin).where(
                    ToolPin.tool_name == tool_name,
                    ToolPin.active == True,
                )
            )
            existing = result.scalar_one_or_none()

            if existing is None:
                pin = ToolPin(
                    tool_name=tool_name,
                    server_name=server_name,
                    description_hash=description_hash,
                    first_seen=now,
                    last_verified=now,
                    active=True,
                )
                session.add(pin)
                await session.commit()
                logger.info("Tool pinned: '%s' hash=%s...", tool_name, description_hash[:8])
            else:
                # Update last_verified timestamp
                existing.last_verified = now
                await session.commit()

        return description_hash

    async def verify(
        self,
        tool_name: str,
        description_hash: str,
    ) -> bool:
        """Verify a tool's description hash against the stored pin.

        Returns True if the hash matches (or if the tool has never been pinned).
        Returns False if the hash has changed (potential rug pull).
        """
        async with self._async_session() as session:
            result = await session.execute(
                select(ToolPin).where(
                    ToolPin.tool_name == tool_name,
                    ToolPin.active == True,
                )
            )
            pin = result.scalar_one_or_none()

        if pin is None:
            # Not pinned yet - allow and this will be registered on next register() call
            return True

        if pin.description_hash == description_hash:
            return True

        logger.error(
            "RUG PULL DETECTED: Tool '%s' description changed! "
            "Expected hash=%s..., got hash=%s...",
            tool_name,
            pin.description_hash[:8],
            description_hash[:8],
        )
        return False

    async def verify_description(
        self,
        tool_name: str,
        description: str,
    ) -> bool:
        """Verify a tool's description text against the stored pin.

        Convenience method that computes the hash internally.
        """
        description_hash = _compute_hash(description)
        return await self.verify(tool_name, description_hash)

    async def list_pins(self) -> list[dict]:
        """Return all active tool pins."""
        async with self._async_session() as session:
            result = await session.execute(
                select(ToolPin).where(ToolPin.active == True)
            )
            pins = result.scalars().all()

        return [
            {
                "tool_name": p.tool_name,
                "server_name": p.server_name,
                "description_hash": p.description_hash,
                "first_seen": p.first_seen.isoformat() if p.first_seen else None,
                "last_verified": p.last_verified.isoformat() if p.last_verified else None,
            }
            for p in pins
        ]

    async def deactivate(self, tool_name: str) -> bool:
        """Deactivate a tool pin (e.g., when a tool is intentionally updated).

        Returns True if a pin was deactivated.
        """
        async with self._async_session() as session:
            result = await session.execute(
                select(ToolPin).where(
                    ToolPin.tool_name == tool_name,
                    ToolPin.active == True,
                )
            )
            pin = result.scalar_one_or_none()
            if pin:
                pin.active = False
                await session.commit()
                logger.info("Tool pin deactivated: '%s'", tool_name)
                return True
        return False
