# bot/database/engine.py
import logging
# ИЗМЕНЕНИЕ: create_async_engine импортируется из sqlalchemy.ext.asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from bot.config import app_config
from bot.constants import DB_MAIN_NAME

# Важно: импортируем все модели, чтобы SQLModel.metadata знала о них
# при вызове create_all. Убедитесь, что этот импорт есть.
from bot import models  # noqa

logger = logging.getLogger(__name__)

DATABASE_FILES = {DB_MAIN_NAME: app_config.DATABASE_FILE}
async_engines = {
    db_name: create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    for db_name, db_file in DATABASE_FILES.items()
}
# Sessionmaker остается прежним, так как мы используем асинхронный движок.
# Это стандартная и правильная практика для async SQLAlchemy.
SessionFactory = sessionmaker(
    async_engines[DB_MAIN_NAME], expire_on_commit=False, class_=AsyncSession
)

# Base больше не нужен, SQLModel - наша новая основа

async def init_db() -> None:
    async with async_engines[DB_MAIN_NAME].begin() as conn:
        # Теперь используется metadata из SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database initialized.")
