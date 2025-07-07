"""Middleware to load and provide user settings to Telegram handlers."""

from collections.abc import Awaitable, Callable
import logging
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject  # Added TelegramObject
from aiogram.types import User as AiogramUser
from sqlmodel.ext.asyncio.session import AsyncSession  # Use SQLModel's AsyncSession for type hint

from .utils import _send_error_response  # Import from local utils

if TYPE_CHECKING:
    from bot.config import Settings  # Import Settings for config type hint
    from bot.services_container import Services  # Import Services

logger = logging.getLogger(__name__)


class UserSettingsMiddleware(BaseMiddleware):
    """Middleware to load user settings and provide them to handlers, along with a translator."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject, # Changed to TelegramObject
        data: dict[str, Any], # Changed to Dict
    ) -> Any:
        """Executes the middleware.

        Loads or creates user settings, merges them into the current session,
        and injects user settings and a translator function into the data dictionary.

        Args:
            handler: The next handler in the chain.
            event: The incoming Telegram event (Message or CallbackQuery).
            data: Data to be passed to the handler.

        Returns:
            The result of the next handler, or None if critical error occurs.
        """
        user_obj: AiogramUser = data["event_from_user"]
        session_obj: AsyncSession = data["session"]
        services: Services = data["services"]  # Get services from workflow_data
        config: Settings = data["config"]  # Get config from workflow_data

        user_settings = services.user_settings_cache.get(user_obj.id)

        if not user_settings:
            # Use services.get_or_create_user_settings
            user_settings = await services.get_or_create_user_settings(user_obj.id, session_obj)

        if not user_settings:  # Should ideally not happen if get_or_create handles fallback
            logger.error("CRITICAL: Could not get or create user settings for user %s", user_obj.id)
            _default_tr = services.get_translator(config.general.default_lang).gettext
            await _send_error_response(
                event, _default_tr("An error occurred. Please try again later."), show_alert_for_callback=True
            )
            return

        try:
            # Ensure the object is associated with the current session if it came from cache
            if user_settings not in session_obj:  # Check if it's already part of the session's identity map
                # Check if it's detached (e.g. from cache and session is different)
                if session_obj.is_active and user_settings in session_obj.identity_map.values():
                    # It is in the identity map of this session already, likely from a previous operation
                    pass  # No merge needed
                else:
                    # If it's not in the current session's identity map, merge it.
                    # This handles cases where the cached object might be from a different session context.
                    user_settings = await session_obj.merge(user_settings)
                    logger.debug("User settings for %s merged into current session.", user_obj.id)

            # Refresh to ensure relationship data is up-to-date for this session
            await session_obj.refresh(user_settings, attribute_names=["muted_users_list"])
            logger.debug("Refreshed muted_users_list for user %s in current session.", user_obj.id)
        except Exception as refresh_e:  # Catch more specific SQLAlchemy errors if possible
            logger.exception(
                "Error merging or refreshing muted_users_list for user %s in session: %s",
                user_obj.id,
                refresh_e,
            )
            error_lang_code = (
                user_settings.language_code
                if user_settings and hasattr(user_settings, "language_code")
                else config.general.default_lang
            )
            _tr = services.get_translator(error_lang_code).gettext
            await _send_error_response(
                event, _tr("An error occurred. Please try again later."), show_alert_for_callback=True
            )
            return

        data["user_settings"] = user_settings
        # Use services.get_translator
        translator = services.get_translator(user_settings.language_code)
        data["_"] = translator.gettext
        data["translator"] = translator

        return await handler(event, data)
