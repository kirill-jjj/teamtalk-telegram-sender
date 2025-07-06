from logging.config import fileConfig

from sqlalchemy import pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from sqlmodel import SQLModel  # noqa: E402
# from bot.config import app_config # noqa: E402 # <-- MODIFIED: Commented out/removed
# Import models here for Alembic 'autogenerate' support
from bot.models import Admin, Deeplink, MutedUser, SubscribedUser, UserSettings  # noqa: F401, E402

target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.
import os  # noqa: E402

def process_revision_directives(context, revision, directives):
    """
    This hook prevents Alembic from creating empty migration files
    if no actual structural changes are detected.
    """
    if config.cmd_opts.autogenerate and directives[0].upgrade_ops.is_empty():
        directives[:] = []
        print("INFO  [alembic.autogenerate.compare] No structural changes detected.")


def get_db_url():
    # Attempt to get config file from ALEMBIC_ENV_CONFIG_FILE environment variable
    env_var_name = "ALEMBIC_ENV_CONFIG_FILE"
    config_file = os.environ.get(env_var_name)
    config_file_source = f"environment variable {env_var_name}"

    if config_file:
        print(f"INFO  [alembic.env] Found config file specified in environment variable {env_var_name}: '{config_file}'")
    else:
        print(f"INFO  [alembic.env] Environment variable {env_var_name} not set.")
        # Fallback to default if environment variable is not set
        config_file = ".env"
        config_file_source = "default .env (fallback)"

    print(f"INFO  [alembic.env] Attempting to load configuration from: {config_file} (source: {config_file_source})")

    # To import dotenv, we need to ensure it's available.
    # It's a dependency of pydantic-settings, which is in project dependencies.
    from dotenv import dotenv_values

    if not os.path.exists(config_file):
        print(f"WARN  [alembic.env] Config file '{config_file}' not found. Will attempt to proceed without it if defaults suffice or vars are set.")
        env_values = {}
    else:
        env_values = dotenv_values(config_file)

    # Try to get DATABASE_FILE from loaded .env, then from environment variables as a fallback
    db_file_name = env_values.get("DATABASE_FILE")
    if not db_file_name:
        db_file_name = os.environ.get("DATABASE_FILE") # Fallback to actual env var

    if not db_file_name:
        error_message = (
            f"'DATABASE_FILE' not found. Please ensure it is set in the "
            f"configuration file ('{config_file}', source: {config_file_source}) "
            f"or as an environment variable."
        )
        print(f"ERROR [alembic.env] {error_message}")
        raise ValueError(error_message)

    db_path = os.path.abspath(db_file_name)
    db_url = f"sqlite+aiosqlite:///{db_path}"
    print(f"INFO  [alembic.env] Using database URL: {db_url} (from DATABASE_FILE='{db_file_name}', source_config_file='{config_file}')")
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
        render_as_batch=True
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    """Run migrations in 'online' mode using an asyncio event loop."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = get_db_url()

    connectable = create_async_engine(
        db_url,
        poolclass=pool.NullPool,
        future=True, # Ensure to use the new style execution
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        process_revision_directives=process_revision_directives,
        render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio
    asyncio.run(run_migrations_online_async())