# Название файла: bot/telegram_bot/middlewares/admin_check.py

import logging
from typing import Callable, Coroutine, Any, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, CallbackQuery, Message

# Для типизации
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)

class AdminCheckMiddleware(BaseMiddleware):
    """
    Этот middleware проверяет, является ли пользователь, вызвавший команду или нажавший кнопку, администратором.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Проверяем, что у нас есть пользователь, от которого пришло событие
        user = data.get("event_from_user")
        if not user:
            # Если пользователя нет в data (маловероятно для Message/CallbackQuery с from_user),
            # то мы не можем проверить права. Пропускаем дальше.
            # Это может быть, например, для channel_post или других типов обновлений.
            logger.debug("AdminCheckMiddleware: No 'event_from_user' in data. Skipping check.")
            return await handler(event, data)

        app: "Application" = data["app"]

        # Проверяем ID пользователя по кешу администраторов
        if user.id not in app.admin_ids_cache:
            # Если это CallbackQuery, отвечаем на него
            if isinstance(event, CallbackQuery):
                # Попытаемся получить переводчик из data, если он там есть
                # (например, добавлен UserSettingsMiddleware)
                translator = data.get("translator")
                if not translator: # Если нет, берем дефолтный из app
                    logger.warning("AdminCheckMiddleware: Translator not found in data for CallbackQuery. Using default.")
                    translator = app.get_translator() # Предполагается, что get_translator без аргументов вернет дефолтный
                _ = translator.gettext

                await event.answer(_("You are not authorized to perform this action."), show_alert=True)
                logger.warning(f"Unauthorized access denied for user {user.id} (Username: {user.username}) in CallbackQuery to event: {type(event).__name__}.")
                return # Останавливаем обработку

            # Если это Message, можно либо проигнорировать, либо ответить
            # В нашем случае команды админа должны отвечать об ошибке
            if isinstance(event, Message):
                _ = data.get("_") # gettext функция должна быть в data от UserSettingsMiddleware
                if _: # Если функция перевода есть
                    await event.reply(_("You are not authorized to perform this action."))
                else: # Фоллбэк, если функции перевода нет
                    logger.warning("AdminCheckMiddleware: Translator function '_' not found in data for Message. Replying with default lang.")
                    # Получаем дефолтный переводчик и отвечаем
                    default_translator = app.get_translator() # Предполагается, что get_translator без аргументов вернет дефолтный
                    await event.reply(default_translator.gettext("You are not authorized to perform this action."))

                logger.warning(f"Unauthorized access denied for user {user.id} (Username: {user.username}) in Message handler for command: {event.text}.")
                return # Останавливаем обработку

            # Если это не Message и не CallbackQuery, но есть user, логируем и пропускаем
            # (на случай, если middleware будет случайно применен к другим типам событий)
            logger.warning(f"AdminCheckMiddleware: Unauthorized user {user.id} (Username: {user.username}) for unhandled event type {type(event).__name__}. Allowing handler to proceed as behavior is undefined.")


        # Если проверка пройдена, передаем управление дальше
        logger.debug(f"AdminCheckMiddleware: User {user.id} (Username: {user.username}) authorized. Proceeding to handler for {type(event).__name__}.")
        return await handler(event, data)
