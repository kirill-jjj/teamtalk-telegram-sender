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

target_metadata = SQLModel.metadata

import os  # noqa: E402


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
    """Constructs the database URL from configuration.

    Reads configuration from a TOML file specified by an environment variable
    or a default '.env' file.
    Falls back to DATABASE_FILE environment variable if 'database.db_file' is not in TOML.

    Returns:
        The fully constructed SQLite database URL.

    Raises:
        FileNotFoundError: If the configuration file is not found.
        ValueError: If critical configuration keys are missing or invalid.
        OSError: If there's an error reading the configuration file.
    """
    # Attempt to get config file from ALEMBIC_ENV_CONFIG_FILE environment variable
    env_var_name = "ALEMBIC_ENV_CONFIG_FILE"
    config_file = os.environ.get(env_var_name)
    config_file_source = f"environment variable {env_var_name}"

    # Assuming a basic logger might be available or print is fine for Alembic's env.py
    # If advanced logging is set up for alembic, replace with logger.info/error
    if config_file:
        print(  # noqa: T201
            f"INFO  [alembic.env] Found config file specified in environment variable {env_var_name}: '{config_file}'"
        )
    else:
        print(f"INFO  [alembic.env] Environment variable {env_var_name} not set.")  # noqa: T201
        # Fallback to default if environment variable is not set
        config_file = ".env"
        config_file_source = "default .env (fallback)"

    print(f"INFO  [alembic.env] Attempting to load configuration from: {config_file} (source: {config_file_source})")  # noqa: T201

    if not os.path.exists(config_file):
        error_message = f"Alembic configuration file '{config_file}' not found (source: {config_file_source})."
        print(f"ERROR [alembic.env] {error_message}")  # noqa: T201 # Or logger.error
        raise FileNotFoundError(error_message)

    try:
        with open(config_file, "rb") as f:
            config_data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        error_message = f"Error decoding TOML configuration file '{config_file}': {e}"
        print(f"ERROR [alembic.env] {error_message}")  # noqa: T201 # Or logger.error
        raise ValueError(error_message) from e
    except Exception as e:
        error_message = f"Error reading configuration file '{config_file}': {e}"
        print(f"ERROR [alembic.env] {error_message}")  # noqa: T201 # Or logger.error
        raise OSError(error_message) from e

    try:
        db_file_name = config_data["database"]["db_file"]
    except KeyError as e:
        error_message = f"'database.db_file' not found in TOML configuration file '{config_file}'."
        print(f"ERROR [alembic.env] {error_message}")  # noqa: T201 # Or logger.error
        # As a fallback, check environment variable if direct key is missing
        db_file_name_env = os.environ.get("DATABASE_FILE")
        if db_file_name_env:
            print(  # noqa: T201
                f"INFO  [alembic.env] Found DATABASE_FILE in environment variables as fallback: '{db_file_name_env}'"
            )  # Or logger.info
            db_file_name = db_file_name_env
        else:
            raise ValueError(error_message + " Also not found as DATABASE_FILE environment variable.") from e

    if not isinstance(db_file_name, str) or not db_file_name.strip():
        error_message = f"'database.db_file' in '{config_file}' must be a non-empty string. Found: '{db_file_name}'"
        print(f"ERROR [alembic.env] {error_message}")  # noqa: T201 # Or logger.error
        raise ValueError(error_message)

    db_path = os.path.abspath(db_file_name)
    db_url = f"sqlite+aiosqlite:///{db_path}"
    print(  # noqa: T201
        f"INFO  [alembic.env] Using database URL: {db_url} (from key 'database.db_file' in '{config_file}')"
    )  # Or logger.info
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
