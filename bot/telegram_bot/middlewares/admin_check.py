"""Middleware to check if a Telegram user is an administrator."""

from collections.abc import Awaitable, Callable  # Added Awaitable
import gettext  # For translator type hint
import logging

# Для типизации
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as AiogramUser

if TYPE_CHECKING:
    from bot.services_container import Services  # Import Services

logger = logging.getLogger(__name__)


class AdminCheckMiddleware(BaseMiddleware):
    """Этот middleware проверяет, является ли пользователь, вызвавший команду или нажавший кнопку, администратором.

    Relies on 'event_from_user', 'admin_ids_cache', and optionally 'translator' or 'services' being in workflow_data.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Executes the middleware.

        Checks if the user is an admin. If not, and the event is a CallbackQuery or Message,
        it sends an unauthorized message and stops processing. Otherwise, allows admin users
        or unhandled event types to proceed.

        Args:
            handler: The next handler in the chain.
            event: The incoming Telegram event.
            data: Data to be passed to the handler.

        Returns:
            The result of the next handler if authorized, or None if unauthorized.
        """
        user: AiogramUser | None = data.get("event_from_user")
        if not user:
            logger.debug("AdminCheckMiddleware: No 'event_from_user' in data. Skipping check.")
            return await handler(event, data)

        admin_ids_cache: set[int] = data.get("admin_ids_cache", set())

        if user.id not in admin_ids_cache:
            # Initialize translator: try from data, then services, else NullTranslations
            current_translator: gettext.GNUTranslations | gettext.NullTranslations
            translator_from_data = data.get("translator")

            is_valid_translator = isinstance(translator_from_data, gettext.GNUTranslations | gettext.NullTranslations)
            if translator_from_data and is_valid_translator:
                current_translator = translator_from_data
            else:
                services: Services | None = data.get("services")
                if services:
                    user_settings = data.get("user_settings")
                    lang_code = getattr(user_settings, "language_code", None) if user_settings else None
                    current_translator = services.get_translator(lang_code)
                else:
                    logger.warning(
                        "AdminCheckMiddleware: Translator and Services not found in data. Using NullTranslations."
                    )
                    current_translator = gettext.NullTranslations()

            _ = current_translator.gettext
            unauthorized_message = _("You are not authorized to perform this action.")

            if isinstance(event, CallbackQuery):
                await event.answer(unauthorized_message, show_alert=True)
                logger.warning(
                    "Unauthorized access denied for user %s (Username: %s) in CallbackQuery to event: %s.",
                    user.id,
                    user.username,
                    type(event).__name__,
                )
                return  # Stop processing

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
                    "Unauthorized access denied for user %s (Username: %s) in Message handler for command: %s.",
                    user.id,
                    user.username,
                    event.text,
                )
                return  # Stop processing

            logger.warning(
                "AdminCheckMiddleware: Unauthorized user %s (Username: %s) "
                "for unhandled event type %s. Behavior for this event type is undefined.",
                user.id,
                user.username,
                type(event).__name__,
            )
            # Depending on policy, you might want to stop processing here too, or let it pass.
            # For safety, let's stop it.
            return

        logger.debug(
            "AdminCheckMiddleware: User %s (Username: %s) authorized. Proceeding to handler for %s.",
            user.id,
            user.username,
            type(event).__name__,
        )
        return await handler(event, data)
