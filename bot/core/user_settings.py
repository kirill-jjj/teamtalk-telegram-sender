# bot/core/user_settings.py
import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from bot.models import UserSettings  # Импортируем новую единую модель

logger = logging.getLogger(__name__)

# Этот класс больше не нужен, так как UserSettings из bot.models теперь выполняет обе роли.
# class UserSpecificSettings(BaseModel): ...

# Функция для преобразования в строку остается, так как мы храним muted_users как строку.
def _prepare_muted_users_string(users_set: set[str]) -> str:
    if not users_set:
        return ""
    return ",".join(sorted(list(users_set)))

USER_SETTINGS_CACHE: dict[int, UserSettings] = {}

async def load_user_settings_to_cache(session_factory) -> None:
    logger.info("Loading user settings into cache...")
    async with session_factory() as session:
        statement = select(UserSettings)
        # ИЗМЕНЕНИЕ: Возвращаем session.execute
        results = await session.execute(statement)
        user_settings_list = results.scalars().all()
        for settings_row in user_settings_list:
            USER_SETTINGS_CACHE[settings_row.telegram_id] = settings_row
    logger.debug(f"{len(USER_SETTINGS_CACHE)} user settings loaded into cache.")

async def get_or_create_user_settings(telegram_id: int, session: AsyncSession) -> UserSettings:
    if telegram_id in USER_SETTINGS_CACHE:
        return USER_SETTINGS_CACHE[telegram_id]

    user_settings = await session.get(UserSettings, telegram_id)
    if user_settings:
        USER_SETTINGS_CACHE[telegram_id] = user_settings
        return user_settings
    else:
        # Создание нового объекта стало гораздо проще
        new_settings = UserSettings(telegram_id=telegram_id)
        session.add(new_settings)
        try:
            await session.commit()
            await session.refresh(new_settings)
            logger.debug(f"Created default UserSettings row for user {telegram_id} in DB.")
            USER_SETTINGS_CACHE[telegram_id] = new_settings
            return new_settings
        except Exception as e:
            await session.rollback()
            logger.error(f"Error creating default settings for user {telegram_id}: {e}", exc_info=True)
            # Возвращаем временный объект, если сохранение не удалось
            # В этом случае он не будет добавлен в кеш, что корректно, т.к. он не сохранен в БД.
            return UserSettings(telegram_id=telegram_id)


async def update_user_settings_in_db(session: AsyncSession, settings: UserSettings):
    # Обновление теперь тривиально
    # SQLModel объекты, полученные из сессии, уже привязаны к ней.
    # Поэтому session.add() неявно вызывается при изменении атрибутов и последующем session.commit()
    # Однако, явный session.add() также безопасен и может быть полезен, если объект был создан вне сессии.
    session.add(settings)
    try:
        await session.commit()
        await session.refresh(settings)
        USER_SETTINGS_CACHE[settings.telegram_id] = settings
        logger.debug(f"Updated settings for user {settings.telegram_id} in DB and cache.")
    except Exception as e:
        await session.rollback()
        logger.error(f"Error updating settings for user {settings.telegram_id} in DB: {e}", exc_info=True)

# Helper function to remove user from cache - useful for unsubscribing
def remove_user_settings_from_cache(telegram_id: int) -> None:
    if telegram_id in USER_SETTINGS_CACHE:
        del USER_SETTINGS_CACHE[telegram_id]
        logger.debug(f"Removed user settings for {telegram_id} from cache.")
    else:
        logger.debug(f"User settings for {telegram_id} not found in cache for removal.")

# Helper to get the set representation of muted users
def get_muted_users_set(settings: UserSettings) -> set[str]:
    if not settings.muted_users:
        return set()
    return set(settings.muted_users.split(','))

# Helper to update the string representation from the set
def set_muted_users_from_set(settings: UserSettings, users_set: set[str]) -> None:
    settings.muted_users = _prepare_muted_users_string(users_set)
