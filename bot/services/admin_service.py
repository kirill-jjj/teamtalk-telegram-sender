"""Service layer for administrator-related operations."""

import gettext
import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database import crud
from bot.models import MuteListMode, NotificationSetting, UserSettings  # Added MuteListMode, NotificationSetting
from bot.services import user_service  # Will be partially replaced by _utils

from . import _utils  # Import the new utils module

if TYPE_CHECKING:
    import pytalk

    from bot.services_container import Services
    from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)


async def add_admin_full(
    session: AsyncSession,
    telegram_id: int,
    user_settings: UserSettings,
    services: "Services",
) -> bool:
    """Adds an admin to the DB, updates cache, and refreshes bot commands."""
    try:
        if await crud.add_admin(session, telegram_id):  # crud.add_admin handles its own commit
            logger.info("Admin %s added to DB.", telegram_id)
            services.cache.add_admin(telegram_id)
            logger.info("Admin %s added to cache.", telegram_id)

            if user_settings:  # Should always have user_settings if adding admin
                commands_updated = await _utils.update_user_bot_commands(
                    telegram_id, user_settings.language_code, services
                )
                if commands_updated:
                    logger.info("Bot commands updated for new admin %s.", telegram_id)
                else:
                    logger.warning("Failed to update bot commands for new admin %s.", telegram_id)
            else:
                logger.warning("User settings not available for new admin %s, commands not updated.", telegram_id)
            return True
        logger.warning("Failed to add admin %s to DB (possibly already admin or DB error).", telegram_id)
    except Exception:
        logger.exception("Error in add_admin_full for telegram_id %s.", telegram_id)
        # crud.add_admin should manage its own session rollback on error.
        return False
    else:
        return False  # This path is reached if crud.add_admin returns False


async def remove_admin_full(
    session: AsyncSession,
    telegram_id: int,
    user_settings: UserSettings,
    services: "Services",
) -> bool:
    """Removes an admin from the DB, updates cache, and refreshes bot commands."""
    try:
        if await crud.remove_admin_db(session, telegram_id):  # crud.remove_admin_db handles its own commit
            logger.info("Admin %s removed from DB.", telegram_id)
            services.cache.remove_admin(telegram_id)
            logger.info("Admin %s removed from cache.", telegram_id)

            if user_settings:  # Should always have user_settings
                commands_updated = await _utils.update_user_bot_commands(
                    telegram_id, user_settings.language_code, services
                )
                if commands_updated:
                    logger.info("Bot commands updated for former admin %s.", telegram_id)
                else:
                    logger.warning("Failed to update bot commands for former admin %s.", telegram_id)
            else:
                logger.warning("User settings not available for former admin %s, commands not updated.", telegram_id)
            return True
        logger.warning("Failed to remove admin %s from DB (possibly not an admin or DB error).", telegram_id)
    except Exception:
        logger.exception("Error in remove_admin_full for telegram_id %s.", telegram_id)
        # crud.remove_admin_db should manage its own session rollback on error.
        return False
    else:
        return False  # This path is reached if crud.remove_admin_db returns False


# ruff: noqa: PLR0912, PLR0915
async def ban_and_delete_subscriber(
    session: AsyncSession,
    services: "Services",
    tt_connection: "TeamTalkConnection | None",
    target_telegram_id: int,
    translator: "gettext.GNUTranslations",
) -> tuple[bool, list[str]]:
    """Bans a subscriber by TG ID and TT username (if linked), then deletes their profile."""
    _ = translator.gettext
    ban_messages: list[str] = []
    overall_success = True

    try:
        user_settings = await session.get(UserSettings, target_telegram_id)
        tt_username_to_ban = user_settings.teamtalk_username if user_settings else None

        # Ban Telegram ID
        banned_tg = await crud.add_to_ban_list(
            session, telegram_id=target_telegram_id, reason="Banned by admin via subscriber menu"
        )
        if banned_tg:
            ban_messages.append(_("Telegram ID {telegram_id} banned.").format(telegram_id=target_telegram_id))
        else:
            # If already banned, it's not a "failure" of this operation, but good to note.
            # If DB error, it's a failure. crud.add_to_ban_list should ideally signal this.
            # Assuming it returns False on actual error or if already banned.
            logger.info("Telegram ID %s might already be banned or DB error occurred.", target_telegram_id)

        # Ban TeamTalk username
        if tt_username_to_ban:
            banned_tt = await crud.add_to_ban_list(
                session,
                teamtalk_username=tt_username_to_ban,
                reason=f"Banned by admin (linked to TG ID: {target_telegram_id})",
            )
            if banned_tt:
                ban_messages.append(_("TeamTalk username {tt_username} banned.").format(tt_username=tt_username_to_ban))
            else:
                logger.info("TeamTalk username %s might already be banned or DB error occurred.", tt_username_to_ban)

            # Conceptual TeamTalk server ban (current logic is mostly logging)
            if tt_connection and tt_connection.instance and tt_connection.is_ready:
                try:
                    # Placeholder for actual ban logic if/when implemented in pytalk SDK
                    logger.info(
                        "Conceptual TT ban for %s on %s (not in SDK by username).",  # Shortened
                        tt_username_to_ban,
                        tt_connection.server_info.host,
                    )
                except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError):
                    logger.exception(
                        "Error during conceptual TeamTalk ban for %s on %s.",
                        tt_username_to_ban,
                        tt_connection.server_info.host,
                    )
                except Exception:  # pylint: disable=broad-except
                    logger.exception(
                        "Unexpected error during conceptual TeamTalk ban for %s on %s.",
                        tt_username_to_ban,
                        tt_connection.server_info.host,
                    )
            elif tt_username_to_ban:  # Ensure username exists before logging skip
                logger.warning(
                    "Skipping conceptual TeamTalk server ban for %s as tt_connection or instance is"
                    " None/invalid/not ready.",
                    tt_username_to_ban,
                )
        # If any ban step failed in a way crud.add_to_ban_list indicates (e.g. returns False on True error)
        # we might set overall_success = False here. For now, assuming add_to_ban_list is idempotent.

        # Delete user profile
        # session commit for bans should happen before delete, or delete_full_user_profile should handle it.
        # delete_full_user_profile handles its own commit for deletions.
        # Let's commit ban list changes before calling delete.
        await session.commit()
        logger.debug("Committed ban list changes for user %s before profile deletion.", target_telegram_id)

        deleted_profile = await user_service.delete_full_user_profile(session, target_telegram_id, services=services)
        if deleted_profile:
            if ban_messages:  # Only add "data deleted" if there were preceding ban messages
                ban_messages.append(_("Subscriber data also deleted."))
            else:  # If no specific ban messages (e.g. user was already banned), but data was deleted.
                ban_messages.append(_("Subscriber data deleted."))
        else:
            ban_messages.append(_("Error deleting subscriber data."))
            overall_success = False  # Deletion failure is a significant issue

        if not ban_messages:  # If nothing happened (e.g. already banned, and delete failed or no data)
            ban_messages.append(_("User already banned or error occurred during processing."))

    except SQLAlchemyError:
        await session.rollback()
        logger.exception("SQLAlchemyError in ban_and_delete_subscriber for %s.", target_telegram_id)
        ban_messages.append(_("Database error during ban operation."))
        overall_success = False
    except Exception:  # pylint: disable=broad-except
        await session.rollback()
        logger.exception("Unexpected error in ban_and_delete_subscriber for %s.", target_telegram_id)
        ban_messages.append(_("An unexpected error occurred."))
        overall_success = False

    return overall_success, ban_messages


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
        if original_status is False and target_user_settings.not_on_online_enabled is True:
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

    return await _utils._update_user_mute_mode_in_db(
        session, services, target_user_settings, new_mode, log_context=" by admin"
    )


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

    updated_settings = await _utils._update_user_language_in_db(
        session, services, target_user_settings, new_lang_code, log_context=" by admin"
    )

    if updated_settings:
        commands_updated = await _utils.update_user_bot_commands(target_telegram_id, new_lang_code, services)
        if not commands_updated:
            logger.warning(
                "Failed to update bot commands for user %s after language change by admin to '%s'.",
                target_telegram_id,
                new_lang_code,
            )
    return updated_settings
