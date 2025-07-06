import logging
from typing import Callable, Coroutine, Any, Dict, TYPE_CHECKING

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, User as AiogramUser
from sqlalchemy.ext.asyncio import AsyncSession

from .utils import _send_error_response # Import from local utils

if TYPE_CHECKING:
    # from sender import Application # No longer needed
    from bot.services_container import Services # Import Services
    from bot.config import Settings # Import Settings for config type hint

logger = logging.getLogger(__name__)

class UserSettingsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_obj: AiogramUser = data["event_from_user"]
        session_obj: AsyncSession = data["session"]
        services: "Services" = data["services"] # Get services from workflow_data
        config: "Settings" = data["config"] # Get config from workflow_data

        user_settings = services.user_settings_cache.get(user_obj.id)

        if not user_settings:
            # Use services.get_or_create_user_settings
            user_settings = await services.get_or_create_user_settings(user_obj.id, session_obj)

        if not user_settings: # Should ideally not happen if get_or_create handles fallback
            logger.error(f"CRITICAL: Could not get or create user settings for user {user_obj.id}")
            # Use services.get_translator and config.DEFAULT_LANG
            _default_tr = services.get_translator(config.DEFAULT_LANG).gettext
            await _send_error_response(event, _default_tr("An error occurred. Please try again later."), show_alert_for_callback=True)
            return

        try:
            # Ensure the object is associated with the current session if it came from cache
            if user_settings not in session_obj: # Check if it's already part of the session's identity map
                 # Check if it's detached (e.g. from cache and session is different)
                if session_obj.is_active and user_settings in session_obj.identity_map.values():
                     # It is in the identity map of this session already, likely from a previous operation
                     pass # No merge needed
                else:
                    # If it's not in the current session's identity map, merge it.
                    # This handles cases where the cached object might be from a different session context.
                    user_settings = await session_obj.merge(user_settings)
                    logger.debug(f"User settings for {user_obj.id} merged into current session.")

            # Refresh to ensure relationship data is up-to-date for this session
            await session_obj.refresh(user_settings, attribute_names=['muted_users_list'])
            logger.debug(f"Refreshed muted_users_list for user {user_obj.id} in current session.")
        except Exception as refresh_e: # Catch more specific SQLAlchemy errors if possible
            logger.error(f"Error merging or refreshing muted_users_list for user {user_obj.id} in session: {refresh_e}", exc_info=True)
            error_lang_code = user_settings.language_code if user_settings and hasattr(user_settings, 'language_code') else config.DEFAULT_LANG
            _tr = services.get_translator(error_lang_code).gettext
            await _send_error_response(event, _tr("An error occurred. Please try again later."), show_alert_for_callback=True)
            return

        data["user_settings"] = user_settings
        # Use services.get_translator
        translator = services.get_translator(user_settings.language_code)
        data["_"] = translator.gettext
        data["translator"] = translator

        return await handler(event, data)
