"""Utilities for programmatic Alembic migration management."""

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from bot.config import Settings

logger = logging.getLogger(__name__)


async def run_migrations(settings: Settings, project_root: Path) -> None:
    """Executes Alembic migrations to the latest version ('head').

    This function programmatically invokes Alembic to update the database schema,
    using the same configuration as the main application.

    Args:
        settings: The loaded application settings object.
        project_root: The root path of the project.
    """
    alembic_ini_path = project_root / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))

    db_file_path = Path(settings.database.db_file)
    if not db_file_path.is_absolute():
        db_file_path = settings._config_dir / db_file_path

    db_path = db_file_path.resolve()
    db_url = f"sqlite+aiosqlite:///{db_path}"

    logger.info("Checking and applying Alembic migrations for DB file: %s", db_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)

    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    try:
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        logger.info("Alembic migrations applied successfully.")
    except Exception:
        logger.exception("An error occurred during Alembic migrations.")
        raise
