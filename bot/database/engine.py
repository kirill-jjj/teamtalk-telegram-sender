# bot/database/engine.py
import logging
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from bot.config import app_config
from bot.constants import DB_MAIN_NAME

from bot import models  # noqa

logger = logging.getLogger(__name__)

DATABASE_FILES = {DB_MAIN_NAME: app_config.DATABASE_FILE}
async_engines = {
    db_name: create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    for db_name, db_file in DATABASE_FILES.items()
}
SessionFactory = sessionmaker(
    async_engines[DB_MAIN_NAME], expire_on_commit=False, class_=AsyncSession
)


async def init_db() -> None:
    async with async_engines[DB_MAIN_NAME].begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database initialized.")
