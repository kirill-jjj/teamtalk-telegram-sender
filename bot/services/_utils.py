# This module will contain shared utility functions for different services.
# It helps to avoid circular dependencies and improve code organization.

import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommandScopeChat
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.models import MuteListMode, UserSettings
from bot.telegram_bot.commands import get_admin_commands, get_user_commands

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


async def _update_user_mute_mode_in_db(
    session: AsyncSession,
    services: "Services",
    settings_to_update: UserSettings,
    new_mode: MuteListMode,
    log_context: str = "",  # For slightly different log messages
) -> UserSettings | None:
    """Private helper to update mute mode, commit, refresh, cache, and handle errors."""
    original_mode = settings_to_update.mute_list_mode
    if original_mode == new_mode:
        return settings_to_update  # No change needed

    try:
        settings_to_update.mute_list_mode = new_mode
        await session.commit()
        await session.refresh(settings_to_update)
        services.cache.update_user_settings(settings_to_update)
        logger.info(
            "Successfully set mute list mode to '%s' for user %s%s. DB and cache updated.",
            new_mode.value,
            settings_to_update.telegram_id,
            log_context,
        )
    except SQLAlchemyError:
        await session.rollback()
        # Revert in-memory change before returning or if the object is re-used
        settings_to_update.mute_list_mode = original_mode
        logger.exception(
            "SQLAlchemyError while setting mute list mode to '%s' for user %s%s. Rolled back.",
            new_mode.value,
            settings_to_update.telegram_id,
            log_context,
        )
        return None
    except Exception:  # Catch any other unexpected errors
        await session.rollback()
        settings_to_update.mute_list_mode = original_mode
        logger.exception(
            "Unexpected error while setting mute list mode to '%s' for user %s%s. Rolled back.",
            new_mode.value,
            settings_to_update.telegram_id,
            log_context,
        )
        return None
    else:
        return settings_to_update


async def _update_user_language_in_db(
    session: AsyncSession,
    services: "Services",
    settings_to_update: UserSettings,
    new_lang_code: str,
    log_context: str = "",
) -> UserSettings | None:
    """Private helper to update language_code, commit, refresh, cache, and handle errors."""
    original_lang_code = settings_to_update.language_code
    if original_lang_code == new_lang_code:
        return settings_to_update  # No change needed

    try:
        settings_to_update.language_code = new_lang_code
        await session.commit()
        await session.refresh(settings_to_update)
        services.cache.update_user_settings(settings_to_update)
        logger.info(
            "Successfully set language to '%s' for user %s%s. DB and cache updated.",
            new_lang_code,
            settings_to_update.telegram_id,
            log_context,
        )
    except SQLAlchemyError:
        await session.rollback()
        settings_to_update.language_code = original_lang_code
        logger.exception(
            "SQLAlchemyError while setting language to '%s' for user %s%s. Rolled back.",
            new_lang_code,
            settings_to_update.telegram_id,
            log_context,
        )
        return None
    except Exception:
        await session.rollback()
        settings_to_update.language_code = original_lang_code
        logger.exception(
            "Unexpected error while setting language to '%s' for user %s%s. Rolled back.",
            new_lang_code,
            settings_to_update.telegram_id,
            log_context,
        )
        return None
    else:
        return settings_to_update


async def update_user_bot_commands(
    telegram_id: int,
    new_lang_code: str,
    services: "Services",
) -> bool:
    """Updates bot commands for a user based on their new language and admin status."""
    try:
        new_lang_translator = services.get_translator(new_lang_code)
        _ = new_lang_translator.gettext
        is_admin = services.cache.is_admin(telegram_id)
        commands_to_set = get_admin_commands(_) if is_admin else get_user_commands(_)
        scope = BotCommandScopeChat(chat_id=telegram_id)
        active_bot_instance = services.bot_event
        await active_bot_instance.delete_my_commands(scope=scope)
        await active_bot_instance.set_my_commands(commands=commands_to_set, scope=scope)
        logger.info(
            "Successfully updated Telegram commands for user %s to language '%s'. Admin status: %s",
            telegram_id,
            new_lang_code,
            is_admin,
        )
    except TelegramAPIError:
        logger.exception(
            "TelegramAPIError updating commands for user %s to language '%s'.",
            telegram_id,
            new_lang_code,
        )
        return False
    except Exception:
        logger.exception(
            "Unexpected error updating commands for user %s to language '%s'.",
            telegram_id,
            new_lang_code,
        )
        return False
    else:
        return True
