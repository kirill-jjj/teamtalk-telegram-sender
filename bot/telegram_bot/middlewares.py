import logging
from collections.abc import Callable, Coroutine
from typing import Any

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from bot.core.user_settings import (
    UserSpecificSettings,
    get_or_create_user_settings,
)
from bot.teamtalk_bot import (
    bot_instance as tt_bot_module,
)  # Импортируем сам модуль

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: sessionmaker):  # type: ignore
        super().__init__()
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[
            [TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any],
        ],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            return await handler(event, data)


class UserSettingsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[
            [TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any],
        ],
        event: Message | CallbackQuery,  # Specific events that have a user
        data: dict[str, Any],
    ) -> Any:
        user_obj = data.get("event_from_user")
        session_obj: AsyncSession | None = data.get("session")
        user_specific_settings: UserSpecificSettings

        if user_obj and session_obj:
            telegram_id_val = user_obj.id
            # Use get_or_create_user_settings to ensure settings are loaded/created
            user_specific_settings = await get_or_create_user_settings(
                telegram_id_val, session_obj,
            )
        else:
            # Fallback for events without user or session (should ideally not happen for user-facing handlers)
            user_specific_settings = UserSpecificSettings()
            logger.warning(
                f"UserSettingsMiddleware: No user or session for event {type(event)}. Using default settings.",
            )

        data["user_specific_settings"] = user_specific_settings
        # For convenience, also pass individual common settings
        data["language"] = user_specific_settings.language
        data["notification_settings_enum"] = (
            user_specific_settings.notification_settings
        )  # Pass the enum itself
        data["mute_settings_dict"] = {  # Pass as a dict
            "muted_users": user_specific_settings.muted_users_set,
            "mute_all": user_specific_settings.mute_all_flag,
        }
        return await handler(event, data)


import logging  # Убедитесь, что logging импортирован в этом файле
from collections.abc import Callable, Coroutine
from typing import Any

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import TelegramObject

# ... другие ваши импорты ...

logger = logging.getLogger(
    __name__,
)  # Инициализация логгера для этого модуля, если еще не сделано


# ...


class TeamTalkInstanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[
            [TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any],
        ],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        actual_tt_instance = tt_bot_module.current_tt_instance
        data["tt_instance"] = actual_tt_instance
        return await handler(event, data)
