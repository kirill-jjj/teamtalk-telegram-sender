"""Service layer for user-related operations, like profile deletion."""

import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommandScopeChat
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession  # Changed to SQLModel's AsyncSession

from bot.core.user_settings import update_user_settings_in_db
from bot.database import crud
from bot.models import MutedUser, MuteListMode, NotificationSetting, SubscribedUser, UserSettings  # Added MuteListMode
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


async def admin_toggle_noon_setting(
    session: AsyncSession,
    services: "Services",
    target_telegram_id: int,
) -> UserSettings | None:
    """Toggles the NOON (Not On Online Notifications) setting for a target user.

    Handles DB session, commit, rollback, and cache update.
    Returns the updated UserSettings object or None on failure.
    """
    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        logger.warning("admin_toggle_noon_setting: UserSettings not found for %s", target_telegram_id)
        return None

    original_status = target_user_settings.not_on_online_enabled
    try:
        target_user_settings.not_on_online_enabled = not target_user_settings.not_on_online_enabled
        if target_user_settings.not_on_online_enabled:
            target_user_settings.not_on_online_confirmed = True

        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        logger.info(
            "Successfully toggled NOON setting for user %s to %s. DB and cache updated.",
            target_telegram_id,
            target_user_settings.not_on_online_enabled,
        )
    except SQLAlchemyError:
        await session.rollback()
        target_user_settings.not_on_online_enabled = original_status
        if (
            original_status is False and target_user_settings.not_on_online_enabled is True
        ):
            target_user_settings.not_on_online_confirmed = False
        logger.exception(
            "SQLAlchemyError while toggling NOON setting for user %s. Rolled back.",
            target_telegram_id,
        )
        return None
    except Exception:
        await session.rollback()
        target_user_settings.not_on_online_enabled = original_status
        if original_status is False and target_user_settings.not_on_online_enabled is True:
             target_user_settings.not_on_online_confirmed = False
        logger.exception(
            "Unexpected error while toggling NOON setting for user %s. Rolled back.",
            target_telegram_id,
        )
        return None
    else:
        return target_user_settings


async def set_user_mute_mode(
    session: AsyncSession,
    services: "Services",
    user_settings: UserSettings,
    new_mode: "MuteListMode",
) -> UserSettings | None:
    """Sets the mute list mode for the user themselves."""
    managed_user_settings = await session.merge(user_settings)
    if not managed_user_settings:
        logger.error("set_user_mute_mode: Failed to merge user_settings for TG ID %s.", user_settings.telegram_id)
        return None

    original_mode = managed_user_settings.mute_list_mode
    if original_mode == new_mode:
        return managed_user_settings

    try:
        managed_user_settings.mute_list_mode = new_mode
        await session.commit()
        await session.refresh(managed_user_settings)
        services.cache.update_user_settings(managed_user_settings)
        logger.info(
            "Successfully set mute list mode to '%s' for user %s (self). DB and cache updated.",
            new_mode.value,
            managed_user_settings.telegram_id,
        )
    except SQLAlchemyError:
        await session.rollback()
        managed_user_settings.mute_list_mode = original_mode
        logger.exception(
            "SQLAlchemyError while setting mute list mode to '%s' for user %s (self). Rolled back.",
            new_mode.value,
            managed_user_settings.telegram_id,
        )
        return None
    except Exception:
        await session.rollback()
        managed_user_settings.mute_list_mode = original_mode
        logger.exception(
            "Unexpected error while setting mute list mode to '%s' for user %s (self). Rolled back.",
            new_mode.value,
            managed_user_settings.telegram_id,
        )
        return None
    else:
        return managed_user_settings


async def admin_set_user_mute_mode(
    session: AsyncSession,
    services: "Services",
    target_telegram_id: int,
    new_mode: "MuteListMode",
) -> UserSettings | None:
    """Sets the mute list mode for a target user, managed by an admin."""
    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        logger.warning("admin_set_user_mute_mode: UserSettings not found for %s.", target_telegram_id)
        return None

    original_mode = target_user_settings.mute_list_mode
    try:
        target_user_settings.mute_list_mode = new_mode
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        logger.info(
            "Successfully set mute list mode to '%s' for user %s by admin. DB and cache updated.",
            new_mode.value,
            target_telegram_id,
        )
    except SQLAlchemyError:
        await session.rollback()
        target_user_settings.mute_list_mode = original_mode
        logger.exception(
            "SQLAlchemyError while setting mute list mode to '%s' for user %s by admin. Rolled back.",
            new_mode.value,
            target_telegram_id,
        )
        return None
    except Exception:
        await session.rollback()
        target_user_settings.mute_list_mode = original_mode
        logger.exception(
            "Unexpected error while setting mute list mode to '%s' for user %s by admin. Rolled back.",
            new_mode.value,
            target_telegram_id,
        )
        return None
    else:
        return target_user_settings


async def admin_set_user_notification_preference(
    session: AsyncSession,
    services: "Services",
    target_telegram_id: int,
    new_pref_enum: "NotificationSetting",
) -> UserSettings | None:
    """Sets the notification preference for a target user, managed by an admin."""
    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        logger.warning("admin_set_user_notification_preference: UserSettings not found for %s.", target_telegram_id)
        return None

    original_pref = target_user_settings.notification_settings
    try:
        target_user_settings.notification_settings = new_pref_enum
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        logger.info(
            "Successfully set notification preference to '%s' for user %s by admin. DB and cache updated.",
            new_pref_enum.value,
            target_telegram_id,
        )
    except SQLAlchemyError:
        await session.rollback()
        target_user_settings.notification_settings = original_pref
        logger.exception(
            "SQLAlchemyError while setting notification preference to '%s' for user %s by admin. Rolled back.",
            new_pref_enum.value,
            target_telegram_id,
        )
        return None
    except Exception:
        await session.rollback()
        target_user_settings.notification_settings = original_pref
        logger.exception(
            "Unexpected error while setting notification preference to '%s' for user %s by admin. Rolled back.",
            new_pref_enum.value,
            target_telegram_id,
        )
        return None
    else:
        return target_user_settings


async def admin_link_tt_account(
    session: AsyncSession,
    services: "Services",
    target_telegram_id: int,
    tt_username_to_link: str,
) -> tuple[UserSettings | None, str]:
    """Links a TeamTalk account to a subscriber, managed by an admin."""
    if await crud.is_teamtalk_username_banned(session, tt_username_to_link):
        logger.warning(
            "Attempt to link banned TeamTalk username '%s' to user %s.",
            tt_username_to_link,
            target_telegram_id,
        )
        return None, "banned"

    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        logger.warning("admin_link_tt_account: UserSettings not found for %s.", target_telegram_id)
        return None, "not_found"

    original_tt_username = target_user_settings.teamtalk_username
    try:
        target_user_settings.teamtalk_username = tt_username_to_link
        target_user_settings.not_on_online_confirmed = True
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        logger.info(
            "Successfully linked TT username '%s' to user %s (was '%s'). DB and cache updated.",
            tt_username_to_link,
            target_telegram_id,
            original_tt_username,
        )
        status_key = "relinked" if original_tt_username and original_tt_username != tt_username_to_link else "linked"
    except SQLAlchemyError:
        await session.rollback()
        target_user_settings.teamtalk_username = original_tt_username
        logger.exception(
            "SQLAlchemyError while linking TT username '%s' for user %s. Rolled back.",
            tt_username_to_link,
            target_telegram_id,
        )
        return None, "error"
    except Exception:
        await session.rollback()
        target_user_settings.teamtalk_username = original_tt_username
        logger.exception(
            "Unexpected error while linking TT username '%s' for user %s. Rolled back.",
            tt_username_to_link,
            target_telegram_id,
        )
        return None, "error"
    else:
        return target_user_settings, status_key


async def admin_set_user_language(
    session: AsyncSession,
    services: "Services",
    target_telegram_id: int,
    new_lang_code: str,
) -> UserSettings | None:
    """Sets the language for a target user, managed by an admin."""
    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        logger.warning("admin_set_user_language: UserSettings not found for %s.", target_telegram_id)
        return None

    original_lang_code = target_user_settings.language_code
    try:
        target_user_settings.language_code = new_lang_code
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        logger.info(
            "Successfully set language to '%s' for user %s by admin. DB and cache updated.",
            new_lang_code,
            target_telegram_id,
        )
        commands_updated = await update_user_bot_commands(target_telegram_id, new_lang_code, services)
        if not commands_updated:
            logger.warning(
                "Failed to update bot commands for user %s after language change by admin to '%s'.",
                target_telegram_id,
                new_lang_code,
            )
    except SQLAlchemyError:
        await session.rollback()
        target_user_settings.language_code = original_lang_code
        logger.exception(
            "SQLAlchemyError while setting language to '%s' for user %s by admin. Rolled back.",
            new_lang_code,
            target_telegram_id,
        )
        return None
    except Exception:
        await session.rollback()
        target_user_settings.language_code = original_lang_code
        logger.exception(
            "Unexpected error while setting language to '%s' for user %s by admin. Rolled back.",
            new_lang_code,
            target_telegram_id,
        )
        return None
    else:
        return target_user_settings


async def update_user_language_settings(
    session: AsyncSession,
    user_settings: UserSettings,
    new_lang_code: str,
    services: "Services",
) -> bool:
    """Updates user language in settings object, DB, and cache."""
    user_settings.language_code = new_lang_code
    try:
        await update_user_settings_in_db(session, user_settings)
        services.cache.update_user_settings(user_settings)
        logger.info(
            "Successfully updated language to '%s' for user %s in DB and cache.",
            new_lang_code,
            user_settings.telegram_id,
        )
    except SQLAlchemyError:
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
    else: # Corresponds to the main try block
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
