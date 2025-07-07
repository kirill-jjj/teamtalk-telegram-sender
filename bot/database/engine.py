"""Database engine and session factory setup."""

# bot/database/engine.py
import logging
import os  # Moved here for PLC0415

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from bot import models  # Important for SQLModel to discover models
from bot.config import Settings  # Needed for config type hint

logger = logging.getLogger(__name__)


def create_session_factory(config: Settings) -> sessionmaker:
    """Creates and returns a new session factory based on the provided configuration."""
    # This import is needed for SQLModel/Alembic to correctly see all tables.
    # The variable `_` is used to prevent linters from complaining about an unused import.
    _ = models

    absolute_db_path = os.path.abspath(config.database.db_file)  # os will be available
    db_url = f"sqlite+aiosqlite:///{absolute_db_path}"
    logger.info("Creating database engine for: %s", db_url)

    engine = create_async_engine(db_url)

    # expire_on_commit=False is standard practice for asynchronous applications,
    # so that objects do not become "detached" from the session after a commit.
    session_factory = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    return session_factory
