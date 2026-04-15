"""Database initialization and migrations."""
import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .models import Base
from ..config import settings

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Initialize the database, creating all tables."""
    # Ensure the data directory exists
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    logger.info("Database initialized at %s", settings.database_url)


async def get_engine():
    """Create and return an async engine."""
    engine = create_async_engine(settings.database_url, echo=False)
    return engine


async def get_session(engine):
    """Create and return a session factory."""
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(init_db())
