"""Database engine and session factory setup."""

from collections.abc import Callable
import logging
from pathlib import Path
from typing import TypeAlias  # For sessionmaker type hint

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from bot import models  # Important for SQLModel to discover models
from bot.config import Settings

logger = logging.getLogger(__name__)

# Define a type alias for the specific sessionmaker we're creating
# It's a sessionmaker that produces AsyncSession instances
# Loosen the type for the factory itself, as the internals are complex for mypy here.
AsyncSessionFactoryType: TypeAlias = Callable[[], AsyncSession]


def create_session_factory(config: Settings) -> AsyncSessionFactoryType:
    """Creates and returns a new session factory based on the provided configuration."""
    # This import is needed for SQLModel/Alembic to correctly see all tables.
    # The variable `_` is used to prevent linters from complaining about an unused
    # import.
    _ = models

    db_file_path = Path(config.database.db_file)
    if not db_file_path.is_absolute():
        # Assumes the path is relative to the project root if not absolute.
        project_root = Path(__file__).resolve().parent.parent
        db_file_path = project_root / db_file_path

    db_path = db_file_path.resolve()
    db_url = f"sqlite+aiosqlite:///{db_path}"
    logger.info("Creating database engine for: %s", db_url)

    engine = create_async_engine(db_url)

    # expire_on_commit=False is standard practice for asynchronous applications,
    # so that objects do not become "detached" from the session after a commit.
    # Use keyword arguments for clarity and to match mypy's expected signature
    # when class_ is specified.
    return sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[no-any-return, call-overload]
