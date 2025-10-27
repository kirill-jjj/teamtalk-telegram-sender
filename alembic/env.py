"""Alembic environment configuration script."""

from collections.abc import Iterable
import logging
import os
from pathlib import Path

from alembic import context
from alembic.operations.ops import MigrationScript
from alembic.runtime.migration import MigrationContext
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from bot.config import Settings

# Import models here for Alembic 'autogenerate' support
from bot.database.models import (  # noqa: F401
    Admin,
    Deeplink,
    MutedUser,
    SubscribedUser,
    UserSettings,
)

logger = logging.getLogger(__name__)

config = context.config


target_metadata = SQLModel.metadata

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


def prevent_empty_revisions(
    context: MigrationContext,
    revision: str | Iterable[str | None],
    directives: list[MigrationScript],
) -> None:
    """This hook prevents Alembic from creating empty migration files.

    It checks if no actual structural changes are detected during autogenerate.
    """
    # The arguments context and revision are not used in this function,
    # but they are part of the signature required by Alembic.
    # We can mark them as unused if preferred, e.g., by prefixing with an underscore.
    _ = context
    _ = revision
    # Guard against cmd_opts being None and upgrade_ops being None
    if (
        config.cmd_opts is not None
        and config.cmd_opts.autogenerate
        and directives[0].upgrade_ops is not None
        and directives[0].upgrade_ops.is_empty()
    ):
        directives[:] = []
        logger.info(
            "INFO  [alembic.autogenerate.compare] No structural changes detected."
        )


def get_db_url() -> str:
    """Constructs the database URL for Alembic.

    It first attempts to retrieve the URL from Alembic's context (set by the
    application). If not found, it checks the APP_CONFIG_FILE environment
    variable. If still not found, it falls back to loading the default
    application's configuration file.

    Returns:
        str: The fully constructed SQLite database URL.

    Raises:
        FileNotFoundError: If the configuration file is not found during fallback.
        ValueError: If critical configuration keys are missing or invalid during
            fallback.
    """
    # 1. Try to get the URL from Alembic's context (set by the application's
    # programmatic invocation)
    url = context.config.get_main_option("sqlalchemy.url")
    if url:
        logger.info("Using database URL from Alembic context: %s", url)
        return url

    # 2. Fallback: Check APP_CONFIG_FILE environment variable (set by
    # scripts/run_alembic.py)
    config_file_str = os.environ.get("APP_CONFIG_FILE")
    if config_file_str:
        config_file = Path(config_file_str)
        logger.info(
            "Attempting to load configuration from APP_CONFIG_FILE: %s", config_file
        )
    else:
        # 3. Fallback: If not set in context or env var, load from default
        # application config
        config_file = DEFAULT_CONFIG_PATH
        logger.info(
            "Attempting to load configuration from default path: %s", config_file
        )

    try:
        settings = Settings.from_toml(str(config_file))  # Ensure it's a string for mypy
    except FileNotFoundError:
        logger.exception("Configuration file '%s' not found.", config_file)
        raise
    except ValueError:  # Covers TOMLDecodeError and other Pydantic validation errors
        logger.exception("Error loading configuration from '%s'", config_file)
        raise

    db_file_name = settings.database.db_file

    if not isinstance(db_file_name, str) or not db_file_name.strip():
        error_message = (
            f"'database.db_file' in '{config_file}' must be a non-empty string. "
            f"Found: '{db_file_name}'"
        )
        logger.error(error_message)
        raise ValueError(error_message)

    db_path_obj = Path(db_file_name)
    db_path = (
        (PROJECT_ROOT / db_file_name).resolve()
        if not db_path_obj.is_absolute()
        else db_path_obj.resolve()
    )

    db_url = f"sqlite+aiosqlite:///{db_path}"  # f-string for URL construction is fine
    logger.info(
        "Using database URL: %s (from 'database.db_file' in '%s')", db_url, config_file
    )
    return db_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine
    creation, we don't even need a DBAPI to be available.
    """
    url = get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        process_revision_directives=prevent_empty_revisions,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    """Run migrations in 'online' mode using an asyncio event loop.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    db_url = get_db_url()

    connectable = create_async_engine(
        db_url,
        poolclass=pool.NullPool,
        future=True,  # Ensure to use the new style execution
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    Args:
        connection: An active SQLAlchemy connection object.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        process_revision_directives=prevent_empty_revisions,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online_async())
