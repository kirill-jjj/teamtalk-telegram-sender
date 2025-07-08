"""Alembic environment configuration script."""

from logging.config import fileConfig
import tomllib  # Python 3.11+ - Moved here for PLC0415

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine  # Moved here for PLC0415

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from sqlmodel import SQLModel  # noqa: E402

# Import models here for Alembic 'autogenerate' support
from bot.models import Admin, Deeplink, MutedUser, SubscribedUser, UserSettings  # noqa: F401, E402
from bot.config import Settings # Import the Settings model
import os # For path operations

target_metadata = SQLModel.metadata

# Determine the root directory of the project to correctly locate config.toml
# Assuming env.py is in alembic/ and config.toml is in the root.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.toml")


def process_revision_directives(context, revision, directives):
    """This hook prevents Alembic from creating empty migration files.

    It checks if no actual structural changes are detected during autogenerate.
    """
    if config.cmd_opts.autogenerate and directives[0].upgrade_ops.is_empty():
        directives[:] = []
        # Use logging if a logger is configured for Alembic, otherwise print is common in env.py
        # For this refactor, we'll assume print is acceptable here or to be replaced by Alembic's logger if integrated.
        # If a specific logger was intended, it should be configured and used.
        # For now, retaining print as it's often part of Alembic's direct feedback mechanism.
        print("INFO  [alembic.autogenerate.compare] No structural changes detected.")  # noqa: T201


def get_db_url() -> str:
    """Constructs the database URL from 'config.toml' using the Settings model.

    Returns:
        The fully constructed SQLite database URL.

    Raises:
        FileNotFoundError: If 'config.toml' is not found.
        ValueError: If critical configuration keys are missing or invalid.
    """
    config_file = os.environ.get("APP_CONFIG_FILE", DEFAULT_CONFIG_PATH)
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

    # Ensure db_file_name is an absolute path if it's relative
    # It's generally better if config.toml specifies paths relative to the project root or absolute paths.
    # If db_file in config.toml is like "bot_data.db", it will be relative to where alembic is run.
    # To make it relative to project root, we can do:
    if not os.path.isabs(db_file_name):
        db_path = os.path.join(PROJECT_ROOT, db_file_name)
        db_path = os.path.abspath(db_path) # Normalize
    else:
        db_path = db_file_name

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


def do_run_migrations(connection):
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
