"""Alembic environment configuration script."""

from logging.config import fileConfig
import os  # For path operations
from pathlib import Path  # Added for Path operations

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine  # Moved here for PLC0415
from sqlmodel import SQLModel

from bot.config import Settings  # Import the Settings model

# Import models here for Alembic 'autogenerate' support
from bot.models import Admin, Deeplink, MutedUser, SubscribedUser, UserSettings  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = SQLModel.metadata

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


def process_revision_directives(
    context: context.MigrationContext, revision: str, directives: list[context.MigrationScript]
) -> None:
    """This hook prevents Alembic from creating empty migration files.

    It checks if no actual structural changes are detected during autogenerate.
    """
    # The arguments context and revision are not used in this function,
    # but they are part of the signature required by Alembic.
    # We can mark them as unused if preferred, e.g., by prefixing with an underscore.
    _ = context  # Mark as unused
    _ = revision  # Mark as unused
    if config.cmd_opts.autogenerate and directives[0].upgrade_ops.is_empty():
        directives[:] = []
        print("INFO  [alembic.autogenerate.compare] No structural changes detected.")  # noqa: T201


def get_db_url() -> str:
    """
    if config.cmd_opts.autogenerate and directives[0].upgrade_ops.is_empty():
        directives[:] = []
        print("INFO  [alembic.autogenerate.compare] No structural changes detected.")  # noqa: T201


def get_db_url() -> str:
    """Constructs the database URL from 'config.toml' using the Settings model.

    Returns:
        The fully constructed SQLite database URL.

    Raises:
        FileNotFoundError: If 'config.toml' is not found.
        ValueError: If critical configuration keys are missing or invalid.
    """
    config_file_str = os.environ.get("APP_CONFIG_FILE", str(DEFAULT_CONFIG_PATH))
    config_file = Path(config_file_str)
    print(f"INFO  [alembic.env] Attempting to load configuration from: {config_file}") # noqa: T201

    try:
        settings = Settings.from_toml(config_file)
    except FileNotFoundError:
        print(f"ERROR [alembic.env] Configuration file '{config_file}' not found.") # noqa: T201
        raise
    except ValueError as e: # Covers TOMLDecodeError and other Pydantic validation errors
        print(f"ERROR [alembic.env] Error loading configuration from '{config_file}': {e}") # noqa: T201
        raise

    db_file_name = settings.database.db_file

    if not isinstance(db_file_name, str) or not db_file_name.strip():
        error_message = f"'database.db_file' in '{config_file}' must be a non-empty string. Found: '{db_file_name}'"
        print(f"ERROR [alembic.env] {error_message}")  # noqa: T201
        raise ValueError(error_message)

    db_path_obj = Path(db_file_name)
    if not db_path_obj.is_absolute():
        db_path = (PROJECT_ROOT / db_file_name).resolve()
    else:
        db_path = db_path_obj.resolve()

    db_url = f"sqlite+aiosqlite:///{db_path}"
    print(f"INFO  [alembic.env] Using database URL: {db_url} (from 'database.db_file' in '{config_file}')")  # noqa: T201
    return db_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    """
    url = get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        process_revision_directives=process_revision_directives,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    """Run migrations in 'online' mode using an asyncio event loop."""
    db_url = get_db_url()

    connectable = create_async_engine(
        db_url,
        poolclass=pool.NullPool,
        future=True,  # Ensure to use the new style execution
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def do_run_migrations(connection: pool.Connection) -> None:
    """Runs the migrations within the given database connection context.

    This function is called by `run_migrations_online_async` after establishing
    an asynchronous database connection.

    Args:
        connection: An active SQLAlchemy connection object.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        process_revision_directives=process_revision_directives,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online_async())
