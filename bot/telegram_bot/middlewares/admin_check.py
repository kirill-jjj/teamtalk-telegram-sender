import gettext  # For translator type hint
import logging
from collections.abc import Callable, Coroutine

# Для типизации
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as AiogramUser

if TYPE_CHECKING:
    # from sender import Application # No longer needed
    from bot.services_container import Services  # Import Services

logger = logging.getLogger(__name__)

class AdminCheckMiddleware(BaseMiddleware):
    """
    Этот middleware проверяет, является ли пользователь, вызвавший команду или нажавший кнопку, администратором.
    Relies on 'event_from_user', 'admin_ids_cache', and optionally 'translator' or 'services' being in workflow_data.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: AiogramUser | None = data.get("event_from_user")
        if not user:
            logger.debug("AdminCheckMiddleware: No 'event_from_user' in data. Skipping check.")
            return await handler(event, data)

        admin_ids_cache: set[int] = data.get("admin_ids_cache", set())

        if user.id not in admin_ids_cache:
            translator: gettext.GNUTranslations | None = data.get("translator")

            # Fallback to get translator from services if not directly available
            if not translator:
                services: Services | None = data.get("services")
                if services:
                    # Determine language code for user, or default
                    user_settings = data.get("user_settings") # Might be populated by UserSettingsMiddleware
                    lang_code = user_settings.language_code if user_settings else None
                    translator = services.get_translator(lang_code)
                else:
                    logger.warning(
                        "AdminCheckMiddleware: Translator and Services not found in data. "
                        "Using temporary default translator."
                    )
                    translator = gettext.NullTranslations() # Should not happen in normal flow

            _ = translator.gettext
            unauthorized_message = _("You are not authorized to perform this action.")

            if isinstance(event, CallbackQuery):
                await event.answer(unauthorized_message, show_alert=True)
                logger.warning(
                    f"Unauthorized access denied for user {user.id} (Username: {user.username}) "
                    f"in CallbackQuery to event: {type(event).__name__}."
                )
                return # Stop processing

            if isinstance(event, Message):
                # Check if UserSettingsMiddleware provided a gettext function directly
                # This was the old pattern, new pattern is to use `translator` from above.
                # For backward compatibility during refactor, check for `_` too.
                legacy_tr_func = data.get("_")
                if legacy_tr_func and callable(legacy_tr_func):
                    await event.reply(legacy_tr_func("You are not authorized to perform this action."))
                else:
                    await event.reply(unauthorized_message)

                logger.warning(
                    f"Unauthorized access denied for user {user.id} (Username: {user.username}) "
                    f"in Message handler for command: {event.text}."
                )
                return # Stop processing

            logger.warning(
                f"AdminCheckMiddleware: Unauthorized user {user.id} (Username: {user.username}) "
                f"for unhandled event type {type(event).__name__}. "
                f"Behavior for this event type is undefined."
            )
            # Depending on policy, you might want to stop processing here too, or let it pass.
            # For safety, let's stop it.
            return

        logger.debug(
            f"AdminCheckMiddleware: User {user.id} (Username: {user.username}) authorized. "
            f"Proceeding to handler for {type(event).__name__}."
        )
        return await handler(event, data)
