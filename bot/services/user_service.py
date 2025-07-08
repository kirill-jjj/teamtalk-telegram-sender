"""Service layer for user-related operations, like profile deletion."""

import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession  # Changed to SQLModel's AsyncSession
from aiogram.types import BotCommandScopeChat # For command scope
from aiogram.exceptions import TelegramAPIError # For error handling

from bot.database import crud
from bot.models import UserSettings # For type hinting
from bot.core.user_settings import update_user_settings_in_db # For DB update
from bot.telegram_bot.commands import get_admin_commands, get_user_commands # For commands

if TYPE_CHECKING:
    from bot.services_container import Services  # Import Services

logger = logging.getLogger(__name__)


async def delete_full_user_profile(
    session: AsyncSession,
    telegram_id: int,
    services: "Services",  # Changed from app: "Application"
) -> bool:
    """Orchestrates the full deletion of a user's profile.

    This includes database records and cache entries via the services container.
    """
    logger.info("Attempting to delete full user profile for Telegram ID: %s", telegram_id)
    try:
        user_settings_deleted, subscribed_user_deleted = await crud._delete_user_data_from_db(session, telegram_id)

        if not user_settings_deleted and not subscribed_user_deleted:
            logger.info("No DB data found for Telegram ID %s to delete.", telegram_id)
        else:
            await session.commit()
            logger.debug("Committed DB deletions for %s.", telegram_id)

        # Clear data from caches using CacheService
        services.cache.remove_full_user_profile(telegram_id)
        # Logging for this is now handled within CacheService.remove_full_user_profile

        logger.info(
            "Full user profile deletion process completed for Telegram ID: %s. "
            "DB changes (if any) committed. Caches cleared via CacheService.",
            telegram_id,
        )
        return True

    except SQLAlchemyError as e_sql:
        await session.rollback()
        logger.exception("SQLAlchemyError during full data deletion for %s: %s. Rolling back.", telegram_id, e_sql)
        return False
    except Exception as e:
        await session.rollback()
        logger.exception("Unexpected error during full data deletion for %s: %s. Rolling back.", telegram_id, e)
        return False


async def update_user_language_settings(
    session: AsyncSession,
    user_settings: UserSettings,
    new_lang_code: str,
    services: "Services",
) -> bool:
    """Updates user language in settings object, DB, and cache."""
    user_settings.language_code = new_lang_code
    try:
        await update_user_settings_in_db(session, user_settings)  # Handles session.commit()
        services.cache.update_user_settings(user_settings)
        logger.info(
            "Successfully updated language to '%s' for user %s in DB and cache.",
            new_lang_code,
            user_settings.telegram_id,
        )
        return True
    except SQLAlchemyError as e_db:
        # update_user_settings_in_db should handle rollback on its own error.
        # If commit is outside, then consider rollback here.
        logger.exception(
            "SQLAlchemyError updating language to '%s' for user %s: %s",
            new_lang_code,
            user_settings.telegram_id,
            e_db,
        )
        return False
    except Exception as e:
        logger.exception(
            "Unexpected error updating language to '%s' for user %s: %s",
            new_lang_code,
            user_settings.telegram_id,
            e,
        )
        # Consider rollback if session changes were made before this generic error.
        return False


async def update_user_bot_commands(
    telegram_id: int,
    new_lang_code: str,
    services: "Services",
) -> bool:
    """Updates bot commands for a user based on their new language and admin status."""
    try:
        new_lang_translator = services.get_translator(new_lang_code)
        _ = new_lang_translator.gettext  # Localize gettext for command generation

        is_admin = services.cache.is_admin(telegram_id)
        commands_to_set = get_admin_commands(_) if is_admin else get_user_commands(_)

        scope = BotCommandScopeChat(chat_id=telegram_id)
        active_bot_instance = services.bot_event  # Assuming bot_event is the one for commands

        await active_bot_instance.delete_my_commands(scope=scope)
        await active_bot_instance.set_my_commands(commands=commands_to_set, scope=scope)
        logger.info(
            "Successfully updated Telegram commands for user %s to language '%s'. Admin status: %s",
            telegram_id,
            new_lang_code,
            is_admin,
        )
        return True
    except TelegramAPIError as e_tg:
        logger.exception(
            "TelegramAPIError updating commands for user %s to language '%s': %s",
            telegram_id,
            new_lang_code,
            e_tg,
        )
        return False
    except Exception as e:
        logger.exception(
            "Unexpected error updating commands for user %s to language '%s': %s",
            telegram_id,
            new_lang_code,
            e,
        )
        return False
