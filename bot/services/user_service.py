"""Service layer for user-related operations, like profile deletion."""

import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommandScopeChat
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.user_settings import update_user_settings_in_db
from bot.database import crud
from bot.models import MutedUser, MuteListMode, SubscribedUser, UserSettings
from bot.telegram_bot.commands import get_admin_commands, get_user_commands

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


async def delete_full_user_profile(
    session: AsyncSession,
    telegram_id: int,
    services: "Services",
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

        services.cache.remove_full_user_profile(telegram_id)
        # Logging for this is now handled within CacheService.remove_full_user_profile

        logger.info(
            "Full user profile deletion process completed for Telegram ID: %s. "
            "DB changes (if any) committed. Caches cleared via CacheService.",
            telegram_id,
        )

    except SQLAlchemyError:
        await session.rollback()
        logger.exception("SQLAlchemyError during full data deletion for %s. Rolling back.", telegram_id)
        return False
    except Exception:
        await session.rollback()
        logger.exception("Unexpected error during full data deletion for %s. Rolling back.", telegram_id)
        return False
    else:
        return True


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


async def set_user_mute_mode(
    session: AsyncSession,
    services: "Services",
    user_settings: UserSettings,
    new_mode: MuteListMode,
) -> UserSettings | None:
    """Sets the mute list mode for the user themselves."""
    # Ensure the user_settings object is managed by the current session
    managed_user_settings = await session.merge(user_settings)
    # It's possible merge itself could fail or return an unexpected type if not handled carefully,
    # but typically it returns the managed instance or raises an error.
    # Assuming merge is successful and returns a UserSettings instance.
    if not managed_user_settings:  # Should ideally not happen if user_settings is valid
        logger.error("set_user_mute_mode: Failed to merge user_settings for TG ID %s.", user_settings.telegram_id)
        return None

    return await _update_user_mute_mode_in_db(session, services, managed_user_settings, new_mode, log_context=" (self)")


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
        # The original update_user_language_settings used a helper `update_user_settings_in_db`
        # which might encapsulate session.commit() and session.refresh().
        # For consistency with _update_user_mute_mode_in_db, we'll do it explicitly here.
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


async def update_user_language_settings(  # User-initiated
    session: AsyncSession,
    user_settings: UserSettings,
    new_lang_code: str,
    services: "Services",
) -> UserSettings | None:
    """Updates user language for the user themselves."""
    managed_user_settings = await session.merge(user_settings)
    if not managed_user_settings:
        logger.error(
            "update_user_language_settings: Failed to merge user_settings for TG ID %s.", user_settings.telegram_id
        )
        return None  # Or handle error as appropriate

    updated_settings = await _update_user_language_in_db(
        session, services, managed_user_settings, new_lang_code, log_context=" (self)"
    )
    # The original function also called update_user_bot_commands.
    # This should be consistent for both user and admin paths if it's a general side effect of language change.
    if updated_settings:
        commands_updated = await update_user_bot_commands(updated_settings.telegram_id, new_lang_code, services)
        if not commands_updated:
            logger.warning(
                "Failed to update bot commands for user %s after self-language change to '%s'.",
                updated_settings.telegram_id,
                new_lang_code,
            )
    return updated_settings


async def process_new_subscription(
    session: AsyncSession,
    user_settings: UserSettings,
    tt_username: str,
    services: "Services",
) -> bool:
    """Handles all DB and cache operations for a new subscription via deeplink."""
    try:
        was_newly_added = await crud.add_subscriber(session, user_settings.telegram_id)
        subscribed_user_record = await session.get(SubscribedUser, user_settings.telegram_id)
        if not subscribed_user_record:
            logger.error("Failed to ensure user %s is a subscriber in DB after add attempt.", user_settings.telegram_id)
            return False
        if was_newly_added:
            logger.info("User %s newly subscribed via deeplink.", user_settings.telegram_id)
        else:
            logger.info(
                "User %s re-confirmed subscription via deeplink (was already subscribed).",
                user_settings.telegram_id,
            )
        if not services.cache.is_subscribed(user_settings.telegram_id):
            services.cache.add_subscriber(user_settings.telegram_id)
            logger.info("Added user %s to subscriber cache.", user_settings.telegram_id)

        original_tt_username = user_settings.teamtalk_username
        user_settings.teamtalk_username = tt_username
        user_settings.not_on_online_confirmed = True
        settings_updated = await update_user_settings_in_db(session, user_settings)

        if settings_updated:
            logger.info(
                "User settings updated for %s with TT username '%s' (was '%s').",
                user_settings.telegram_id,
                tt_username,
                original_tt_username,
            )
            services.cache.update_user_settings(user_settings)
            return True
        logger.error(
            "Failed to update user settings in DB for user %s with TT username '%s'.",
            user_settings.telegram_id,
            tt_username,
        )
        # This return False was for when settings_updated is False
        # It should be part of the try's normal flow, not here.
    except Exception:
        logger.exception(
            "Error in process_new_subscription for user %s, tt_username %s.", user_settings.telegram_id, tt_username
        )
        return False
    else:  # Corresponds to the main try block
        # This path is reached if settings_updated is False, and no exception occurred
        return False


async def toggle_mute_status_for_tt_user(
    session: AsyncSession,
    user_settings: UserSettings,
    tt_username_to_toggle: str,
    services: "Services",
) -> tuple[bool, str | None]:
    """Toggles the mute status of a TeamTalk user."""
    resulting_action: str | None = None
    existing_entry: MutedUser | None = None
    if user_settings.muted_users_list is None:
        user_settings.muted_users_list = []
    for muted_user_entry in user_settings.muted_users_list:
        if muted_user_entry.muted_teamtalk_username == tt_username_to_toggle:
            existing_entry = muted_user_entry
            break
    try:
        if existing_entry:
            user_settings.muted_users_list.remove(existing_entry)
            await session.delete(existing_entry)
            resulting_action = "unmuted"
            logger.info(
                "User %s unmuted TeamTalk user '%s'. Pending commit.", user_settings.telegram_id, tt_username_to_toggle
            )
        else:
            new_entry = MutedUser(
                user_settings_telegram_id=user_settings.telegram_id,
                muted_teamtalk_username=tt_username_to_toggle,
            )
            user_settings.muted_users_list.append(new_entry)
            session.add(new_entry)
            resulting_action = "muted"
            logger.info(
                "User %s muted TeamTalk user '%s'. Pending commit.", user_settings.telegram_id, tt_username_to_toggle
            )
        await session.commit()
        await session.refresh(user_settings, attribute_names=["muted_users_list"])
        services.cache.update_user_settings(user_settings)
        logger.info(
            "Successfully toggled mute for '%s' for user %s to '%s'. DB and cache updated.",
            tt_username_to_toggle,
            user_settings.telegram_id,
            resulting_action,
        )
    except SQLAlchemyError:
        await session.rollback()
        logger.exception(
            "SQLAlchemyError while toggling mute status for TT user '%s' for TG user %s. Rolled back.",
            tt_username_to_toggle,
            user_settings.telegram_id,
        )
        return False, None
    except Exception:
        await session.rollback()
        logger.exception(
            "Unexpected error while toggling mute status for TT user '%s' for TG user %s. Rolled back.",
            tt_username_to_toggle,
            user_settings.telegram_id,
        )
        return False, None
    else:
        return True, resulting_action


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
