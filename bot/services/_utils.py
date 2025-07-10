# This module will contain shared utility functions for different services.
# It helps to avoid circular dependencies and improve code organization.

import logging
from typing import TYPE_CHECKING, Any

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommandScopeChat
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession  # Reverted to SQLModel's AsyncSession

from bot.models import UserSettings
from bot.telegram_bot.commands import get_admin_commands, get_user_commands

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


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


async def _update_user_setting_field(
    session: AsyncSession, # Reverted type hint
    services: "Services",
    settings_to_update: UserSettings,
    field_name: str,
    new_value: Any,  # noqa: ANN401
    log_context: str = "",
) -> UserSettings | None:
    """Generic helper to update a field in UserSettings, commit, refresh, cache, and handle errors."""
    original_value = getattr(settings_to_update, field_name)
    if original_value == new_value:
        # For MuteListMode, new_value would be an enum member, original_value also.
        # Their .value might be different if comparing enum member directly with a string.
        # However, Pydantic models usually store the enum member itself if the type hint is the enum.
        # Let's assume direct comparison works for now. If not, this check might need adjustment
        # or specific handling for enum types if new_value is passed as raw value.
        # Given the current functions pass MuteListMode or str, direct comparison should be fine.
        logger.debug(
            "Skipping update for field '%s' for user %s as new value is same as old value%s.",
            field_name,
            settings_to_update.telegram_id,
            log_context,
        )
        return settings_to_update

    try:
        setattr(settings_to_update, field_name, new_value)
        await session.commit()
        await session.refresh(settings_to_update)
        services.cache.update_user_settings(settings_to_update) # Update cache with the modified UserSettings

        # For logging, display .value for enums if new_value is an enum (like MuteListMode)
        display_value = new_value.value if hasattr(new_value, 'value') else new_value

        logger.info(
            "Successfully set field '%s' to '%s' for user %s%s. DB and cache updated.",
            field_name,
            display_value,
            settings_to_update.telegram_id,
            log_context,
        )
    except SQLAlchemyError:
        await session.rollback()
        setattr(settings_to_update, field_name, original_value) # Revert in-memory change

        display_value_err = new_value.value if hasattr(new_value, 'value') else new_value
        logger.exception(
            "SQLAlchemyError while setting field '%s' to '%s' for user %s%s. Rolled back.",
            field_name,
            display_value_err,
            settings_to_update.telegram_id,
            log_context,
        )
        return None
    except Exception:  # Catch any other unexpected errors
        await session.rollback()
        setattr(settings_to_update, field_name, original_value) # Revert in-memory change

        display_value_err = new_value.value if hasattr(new_value, 'value') else new_value
        logger.exception(
            "Unexpected error while setting field '%s' to '%s' for user %s%s. Rolled back.",
            field_name,
            display_value_err,
            settings_to_update.telegram_id,
            log_context,
        )
        return None
    else:
        return settings_to_update
