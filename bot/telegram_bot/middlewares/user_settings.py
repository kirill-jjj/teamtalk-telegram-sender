import logging
from typing import Callable, Coroutine, Any, Dict, TYPE_CHECKING

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, User as AiogramUser
from sqlalchemy.ext.asyncio import AsyncSession

from .utils import _send_error_response # Import from local utils

if TYPE_CHECKING:
    from sender import Application

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
        app: "Application" = data["app"]

        user_settings = app.user_settings_cache.get(user_obj.id)

        if not user_settings:
            user_settings = await app.get_or_create_user_settings(user_obj.id, session_obj)

        if not user_settings:
            logger.error(f"CRITICAL: Could not get or create user settings for user {user_obj.id}")
            _default_tr = app.get_translator(app.app_config.DEFAULT_LANG).gettext
            await _send_error_response(event, _default_tr("An error occurred. Please try again later."), show_alert_for_callback=True)
            return

        try:
            if user_settings not in session_obj:
                user_settings = await session_obj.merge(user_settings)
                logger.debug(f"User settings for {user_obj.id} merged into current session.")

            await session_obj.refresh(user_settings, attribute_names=['muted_users_list'])
            logger.debug(f"Refreshed muted_users_list for user {user_obj.id} in current session.")
        except Exception as refresh_e:
            logger.error(f"Error refreshing muted_users_list for user {user_obj.id} in session: {refresh_e}", exc_info=True)
            error_lang_code = user_settings.language_code if user_settings and hasattr(user_settings, 'language_code') else app.app_config.DEFAULT_LANG
            _tr = app.get_translator(error_lang_code).gettext
            await _send_error_response(event, _tr("An error occurred. Please try again later."), show_alert_for_callback=True)
            return

        data["user_settings"] = user_settings
        translator = app.get_translator(user_settings.language_code)
        data["_"] = translator.gettext
        data["translator"] = translator

        return await handler(event, data)
