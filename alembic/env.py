"""Alembic environment configuration script."""

from collections.abc import Iterable
import logging
from logging.config import fileConfig
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
from bot.models import (  # noqa: F401
    Admin,
    Deeplink,
    MutedUser,
    SubscribedUser,
    UserSettings,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


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
        logging.info(
            "INFO  [alembic.autogenerate.compare] No structural changes detected."
        )


def get_db_url() -> str:
    """Constructs the database URL from settings."""
    settings = Settings()
    # Path is relative to project root if not absolute
    project_root = Path(__file__).resolve().parent.parent
    db_file_path = Path(settings.database.db_file)
    if not db_file_path.is_absolute():
        db_file_path = project_root / db_file_path

    db_path = db_file_path.resolve()
    db_url = f"sqlite+aiosqlite:///{db_path}"
    logging.info("Using database URL: %s", db_url)
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
