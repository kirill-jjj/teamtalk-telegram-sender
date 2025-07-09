"""Service layer for user-related operations, like profile deletion."""

import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommandScopeChat
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession  # Changed to SQLModel's AsyncSession

from bot.core.user_settings import update_user_settings_in_db
from bot.database import crud
from bot.models import MutedUser, SubscribedUser, UserSettings
from bot.telegram_bot.commands import get_admin_commands, get_user_commands

if TYPE_CHECKING:
    from bot.services_container import Services

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
    except SQLAlchemyError:  # Removed 'as e_db'
        # update_user_settings_in_db should handle rollback on its own error.
        # If commit is outside, then consider rollback here.
        logger.exception(
            "SQLAlchemyError updating language to '%s' for user %s.",
            new_lang_code,
            user_settings.telegram_id,
        )
        return False
    else:
        return True


async def process_new_subscription(
    session: AsyncSession,
    user_settings: UserSettings,
    tt_username: str,
    services: "Services",
) -> bool:
    """Handles all DB and cache operations for a new subscription via deeplink."""
    try:
        # Attempt to add the subscriber. crud.add_subscriber returns True if newly added,
        # False if already exists or if a DB error occurred during add.
        was_newly_added = await crud.add_subscriber(session, user_settings.telegram_id)

        # After the attempt, verify if the user is actually subscribed in the DB.
        # This covers both cases: newly added, or already existed.
        # session.get() is the most direct way to check existence after an operation.
        subscribed_user_record = await session.get(SubscribedUser, user_settings.telegram_id)

        if not subscribed_user_record:
            # This means crud.add_subscriber failed for a reason other than "already exists" (e.g., DB error during add)
            # and the user is not in the SubscribedUser table.
            logger.error("Failed to ensure user %s is a subscriber in DB after add attempt.", user_settings.telegram_id)
            return False

        # At this point, user is confirmed to be in SubscribedUser table.
        if was_newly_added:
            logger.info("User %s newly subscribed via deeplink.", user_settings.telegram_id)
        else:
            logger.info(
                "User %s re-confirmed subscription via deeplink (was already subscribed).",
                user_settings.telegram_id,
            )

        # Ensure cache consistency for subscriber status
        if not services.cache.is_subscribed(user_settings.telegram_id):  # Corrected method name
            services.cache.add_subscriber(user_settings.telegram_id)
            logger.info("Added user %s to subscriber cache.", user_settings.telegram_id)

        # Update user settings with TeamTalk username
        original_tt_username = user_settings.teamtalk_username
        user_settings.teamtalk_username = tt_username
        user_settings.not_on_online_confirmed = True  # Deeplink implies confirmation

        # update_user_settings_in_db handles its own commit
        settings_updated = await update_user_settings_in_db(session, user_settings)

        if settings_updated:
            logger.info(
                "User settings updated for %s with TT username '%s' (was '%s').",
                user_settings.telegram_id,
                tt_username,
                original_tt_username,
            )
            services.cache.update_user_settings(user_settings)  # Update cache with new settings
            return True
        # Rollback tt_username change in memory if DB update failed?
        # update_user_settings_in_db should have rolled back the session.
        # The user_settings object in memory would be stale if not refreshed.
        logger.error(
            "Failed to update user settings in DB for user %s with TT username '%s'.",
            user_settings.telegram_id,
            tt_username,
        )

    except Exception:
        logger.exception(
            "Error in process_new_subscription for user %s, tt_username %s.", user_settings.telegram_id, tt_username
        )
        # Ensure session is rolled back if any unhandled exception occurred before commits in crud/update_user_settings
        # However, called functions are expected to manage their own session states.
        return False
    else:
        # This path is reached if settings_updated is False
        return False


async def toggle_mute_status_for_tt_user(
    session: AsyncSession,
    user_settings: UserSettings,
    tt_username_to_toggle: str,
    services: "Services",
) -> tuple[bool, str | None]:
    """Toggles the mute status of a TeamTalk user.

    Manages DB session, commit, rollback, and cache update for
    `user_settings.muted_users_list`.
    Returns a tuple: (success_status: bool, resulting_action: "muted" | "unmuted" | None).
    """
    resulting_action: str | None = None
    # Ensure user_settings.muted_users_list is loaded.
    # If user_settings comes from cache, it should be loaded. If from DB without eager load, it might not be.
    # However, UserSettingsMiddleware is expected to provide a fully loaded UserSettings object.
    # For safety, one might consider a check or ensuring it's loaded if it could be partial.
    # For now, assume it's loaded as per typical usage with SQLModel relationships.

    existing_entry: MutedUser | None = None
    if user_settings.muted_users_list is None:  # Should not happen if relationships are set up
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
            # For SQLModel, adding to session might be enough if back_populates is correct.
            # Or explicitly add to the list:
            user_settings.muted_users_list.append(new_entry)
            session.add(new_entry)
            resulting_action = "muted"
            logger.info(
                "User %s muted TeamTalk user '%s'. Pending commit.", user_settings.telegram_id, tt_username_to_toggle
            )

        await session.commit()
        # Refresh the user_settings object to get the most up-to-date muted_users_list from the DB,
        # especially if the list was manipulated directly by SQLModel relationship mechanics.
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
        await session.rollback()  # Rollback on any other unexpected error during DB operations
        logger.exception(
            "Unexpected error while toggling mute status for TT user '%s' for TG user %s. Rolled back.",
            tt_username_to_toggle,
            user_settings.telegram_id,
        )
        return False, None
    else:
        return True, resulting_action
    # This duplicate except block for Exception was removed as it's already caught above.
    # If a more specific error handling is needed here for other types of exceptions,
    # it should be added. For now, the generic `Exception as e` at the end of the
    # `toggle_mute_status_for_tt_user` function handles unexpected errors.


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
