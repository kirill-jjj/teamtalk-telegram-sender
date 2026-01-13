"""Database engine and session factory setup."""

from collections.abc import Callable
import logging
from pathlib import Path
from typing import TypeAlias  # For sessionmaker type hint

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.config import Settings
from bot.database import models  # Important for SQLModel to discover models

logger = logging.getLogger(__name__)

# Define a type alias for the specific sessionmaker we're creating
# It's a sessionmaker that produces AsyncSession instances
# Loosen the type for the factory itself, as the internals are complex for mypy here.
AsyncSessionFactoryType: TypeAlias = Callable[[], AsyncSession]


def create_engine(config: Settings) -> AsyncEngine:
    """Creates and returns a new async engine based on the provided configuration."""
    # This import is needed for SQLModel/Alembic to correctly see all tables.
    # The variable `_` is used to prevent linters from complaining about an unused
    # import.
    _ = models

    db_file_path = Path(config.database.db_file)
    # Resolve the path relative to the configuration file's directory
    # The `_config_dir` is a private attribute, so we use a type ignore.
    if not db_file_path.is_absolute():
        db_file_path = config._config_dir / db_file_path

    db_path = db_file_path.resolve()
    db_url = f"sqlite+aiosqlite:///{db_path}"
    logger.debug("Creating database engine for: %s", db_url)

    engine = create_async_engine(db_url)

    # Enable WAL mode for all connections created by this engine.
    # This is a critical performance enhancement for SQLite in async applications,
    # as it allows concurrent reads and writes, reducing "database is locked" errors.
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(
        dbapi_connection: DBAPIConnection,
        _connection_record: ConnectionPoolEntry,
    ) -> None:
        """Set SQLite PRAGMA for new connections."""
        # In aiosqlite execute() is async, but here we operate at the raw DBAPI
        # connection level, where it is synchronous.
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
        finally:
            cursor.close()

    # expire_on_commit=False is standard practice for asynchronous applications,
    # so that objects do not become "detached" from the session after a commit.
    # Use keyword arguments for clarity and to match mypy's expected signature
    # when class_ is specified.
    return engine


def create_session_factory(engine: AsyncEngine) -> AsyncSessionFactoryType:
    """Creates and returns a new session factory based on the provided engine."""
    return sessionmaker(  # type: ignore[call-overload, no-any-return]
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
