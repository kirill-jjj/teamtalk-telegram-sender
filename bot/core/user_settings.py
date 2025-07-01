# bot/core/user_settings.py

import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload # <--- ИСПРАВЛЕННЫЙ ИМПОРТ

from bot.models import UserSettings
# from bot.config import app_config # Removed as TTLCache and its TTL are gone

logger = logging.getLogger(__name__)

# Заменяем TTLCache на обычный словарь.
# Он будет хранить настройки постоянно, пока бот работает.
USER_SETTINGS_CACHE: dict[int, UserSettings] = {}


async def load_user_settings_to_cache(session_factory) -> None:
    logger.info("Loading all user settings into cache...")
    async with session_factory() as session:
        # Используем selectinload для "жадной" загрузки связанных данных (списка замученных)
        statement = select(UserSettings).options(selectinload(UserSettings.muted_users_list))
        results = await session.execute(statement)
        user_settings_list = results.scalars().all()
        for settings_row in user_settings_list:
            USER_SETTINGS_CACHE[settings_row.telegram_id] = settings_row
    logger.info(f"{len(USER_SETTINGS_CACHE)} user settings loaded into cache.")


async def get_or_create_user_settings(telegram_id: int, session: AsyncSession) -> UserSettings:
    """
    Получает настройки пользователя из кэша. Если их там нет,
    загружает из БД или создает новые, а затем добавляет в кэш.
    """
    if telegram_id in USER_SETTINGS_CACHE:
        return USER_SETTINGS_CACHE[telegram_id]

    # Если в кэше нет, ищем в БД. "Жадно" загружаем muted_users_list.
    user_settings = await session.get(
        UserSettings,
        telegram_id,
        options=[selectinload(UserSettings.muted_users_list)]
    )
    if user_settings:
        USER_SETTINGS_CACHE[telegram_id] = user_settings
        return user_settings
    else:
        # Создаем новые настройки, если в БД их тоже не было
        new_settings = UserSettings(telegram_id=telegram_id)
        session.add(new_settings)
        try:
            await session.commit()
            await session.refresh(new_settings)
            # "Жадно" загружаем muted_users_list и для нового пользователя
            await session.refresh(new_settings, attribute_names=['muted_users_list'])
            logger.debug(f"Created default UserSettings row for user {telegram_id} in DB.")
            USER_SETTINGS_CACHE[telegram_id] = new_settings
            return new_settings
        except Exception as e:
            await session.rollback()
            logger.error(f"Error creating default settings for user {telegram_id}: {e}", exc_info=True)
            # Возвращаем временный объект в случае ошибки, чтобы бот не упал
            return UserSettings(telegram_id=telegram_id)


async def update_user_settings_in_db(session: AsyncSession, settings: UserSettings):
    session.add(settings)
    try:
        await session.commit()
        await session.refresh(settings)
        # Убедимся, что связанные данные тоже обновлены
        await session.refresh(settings, attribute_names=['muted_users_list'])
        USER_SETTINGS_CACHE[settings.telegram_id] = settings
        logger.debug(f"Updated settings for user {settings.telegram_id} in DB and cache.")
    except Exception as e:
        await session.rollback()
        logger.error(f"Error updating settings for user {settings.telegram_id} in DB: {e}", exc_info=True)


def remove_user_settings_from_cache(telegram_id: int) -> None:
    if telegram_id in USER_SETTINGS_CACHE:
        del USER_SETTINGS_CACHE[telegram_id]
        logger.debug(f"Removed user settings for {telegram_id} from cache.")
    else:
        logger.debug(f"User settings for {telegram_id} not found in cache for removal.")
