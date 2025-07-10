"""Service layer for administrator-related operations."""

import gettext
import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database import crud
from bot.models import MuteListMode, NotificationSetting, OperationResult, UserSettings  # Added OperationResult
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


async def _ban_telegram_user(
    session: AsyncSession, target_telegram_id: int, translator: gettext.GNUTranslations
) -> tuple[bool, str | None]:
    """Bans a Telegram ID and returns success status and a message part."""
    _ = translator.gettext
    try:
        banned_tg = await crud.add_to_ban_list(
            session, telegram_id=target_telegram_id, reason="Banned by admin via subscriber menu"
        )
        if banned_tg:
            return True, _("Telegram ID {telegram_id} banned.").format(telegram_id=target_telegram_id)
        # If already banned or other non-exception failure from crud
        logger.info("Telegram ID %s might already be banned or DB issue prevented ban.", target_telegram_id)
        return True, _("Telegram ID {telegram_id} already banned or could not be re-banned.").format(
            telegram_id=target_telegram_id
        )  # Consider it a success if already banned
    except SQLAlchemyError:
        # session.rollback() will be handled by the main orchestrating function
        logger.exception("SQLAlchemyError while banning Telegram ID %s.", target_telegram_id)
        return False, _("Database error banning Telegram ID {telegram_id}.").format(telegram_id=target_telegram_id)
    except Exception:
        logger.exception("Unexpected error while banning Telegram ID %s.", target_telegram_id)
        return False, _("Unexpected error banning Telegram ID {telegram_id}.").format(telegram_id=target_telegram_id)


async def _ban_teamtalk_user(
    session: AsyncSession, tt_username: str, target_telegram_id: int, translator: gettext.GNUTranslations
) -> tuple[bool, str | None]:
    """Bans a TeamTalk username and returns success status and a message part."""
    _ = translator.gettext
    if not tt_username:  # Should be pre-checked by caller
        return True, None  # No username to ban, not an error for this specific function
    try:
        banned_tt = await crud.add_to_ban_list(
            session,
            teamtalk_username=tt_username,
            reason=f"Banned by admin (linked to TG ID: {target_telegram_id})",
        )
        if banned_tt:
            return True, _("TeamTalk username {tt_username} banned.").format(tt_username=tt_username)
        logger.info("TeamTalk username %s might already be banned or DB issue prevented ban.", tt_username)
        return True, _("TeamTalk username {tt_username} already banned or could not be re-banned.").format(
            tt_username=tt_username
        )  # Consider it a success if already banned
    except SQLAlchemyError:
        logger.exception("SQLAlchemyError while banning TeamTalk username %s.", tt_username)
        return False, _("Database error banning TeamTalk username {tt_username}.").format(tt_username=tt_username)
    except Exception:
        logger.exception("Unexpected error while banning TeamTalk username %s.", tt_username)
        return False, _("Unexpected error banning TeamTalk username {tt_username}.").format(tt_username=tt_username)


async def _attempt_teamtalk_server_ban(  # Renamed for clarity
    tt_connection: "TeamTalkConnection | None",
    tt_username: str,
    target_telegram_id: int,  # For logging context
    translator: gettext.GNUTranslations,
) -> tuple[bool, str | None]:
    """Attempts a conceptual ban on the TeamTalk server. Currently logs only."""
    _ = translator.gettext
    if not tt_username:  # Should be pre-checked by caller
        return True, None  # No username, nothing to do on server

    if tt_connection and tt_connection.instance and tt_connection.is_ready:
        try:
            # Placeholder for actual ban logic if/when implemented in pytalk SDK for banning by username
            # For now, this is a conceptual step.
            logger.info(
                "Conceptual TT server ban attempt for username '%s' (linked to TG ID %s) on server %s. "
                "Actual server-side ban by username not yet supported by SDK.",
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
            # Assuming conceptual success as there's no real operation to fail yet.
            # If actual SDK call is added, success/failure will be based on its result.
            return True, _("Conceptual TeamTalk server ban logged for {tt_username}.").format(tt_username=tt_username)
        except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError):
            logger.exception(
                "Error during conceptual TeamTalk server ban for username '%s' (TG ID %s) on %s.",
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
            return False, _("Error during TeamTalk server interaction for {tt_username}.").format(
                tt_username=tt_username
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Unexpected error during conceptual TeamTalk server ban for username '%s' (TG ID %s) on %s.",
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
            return False, _("Unexpected error during TeamTalk server interaction for {tt_username}.").format(
                tt_username=tt_username
            )
    else:
        logger.warning(
            "Skipping conceptual TeamTalk server ban for username '%s' (TG ID %s) as tt_connection "
            "or instance is None/invalid/not ready.",
            tt_username,
            target_telegram_id,
        )
        return True, _("TeamTalk server interaction skipped for {tt_username} (connection not ready).").format(
            tt_username=tt_username
        )


# ruff: noqa: PLR0912
async def ban_and_delete_subscriber(  # Simplified complexity
    session: AsyncSession,
    services: "Services",
    tt_connection: "TeamTalkConnection | None",
    target_telegram_id: int,
    translator: "gettext.GNUTranslations",
) -> dict[str, dict[str, bool | str | None]]:
    """Orchestrates banning a subscriber (TG ID, TT username in DB, conceptual TT server ban).

    and deleting their profile.
    Returns a dictionary with success status and messages for each step.
    """
    _ = translator.gettext
    results: dict[str, dict[str, bool | str | None]] = {
        "telegram_ban": {"success": False, "message": None},
        "teamtalk_db_ban": {"success": False, "message": None},
        "teamtalk_server_ban": {"success": False, "message": None},
        "profile_deletion": {"success": False, "message": None},
    }
    final_commit_needed = False

    try:
        user_settings = await session.get(UserSettings, target_telegram_id)
        tt_username_to_ban = user_settings.teamtalk_username if user_settings else None

        # Step 1: Ban Telegram ID
        tg_ban_success, tg_ban_msg = await _ban_telegram_user(session, target_telegram_id, translator)
        results["telegram_ban"]["success"] = tg_ban_success
        results["telegram_ban"]["message"] = tg_ban_msg
        if not tg_ban_success:
            raise Exception(f"Telegram ID ban failed: {tg_ban_msg}")  # noqa: TRY002, TRY003, TRY301
        final_commit_needed = True

        # Step 2: Ban TeamTalk username in DB (if exists)
        if tt_username_to_ban:
            tt_db_ban_success, tt_db_ban_msg = await _ban_teamtalk_user(
                session, tt_username_to_ban, target_telegram_id, translator
            )
            results["teamtalk_db_ban"]["success"] = tt_db_ban_success
            results["teamtalk_db_ban"]["message"] = tt_db_ban_msg
            if not tt_db_ban_success:
                raise Exception(f"TeamTalk DB ban failed: {tt_db_ban_msg}")  # noqa: TRY002, TRY003, TRY301
            final_commit_needed = True
        else:
            results["teamtalk_db_ban"]["success"] = True  # Skipped, considered success for this step
            results["teamtalk_db_ban"]["message"] = _("No TeamTalk username linked to ban in DB.")

        # Step 3: Conceptual TeamTalk server ban (if TT username exists)
        # This step is considered best-effort and non-critical for overall success.
        if tt_username_to_ban:
            tt_server_ban_success, tt_server_ban_msg = await _attempt_teamtalk_server_ban(
                tt_connection, tt_username_to_ban, target_telegram_id, translator
            )
            results["teamtalk_server_ban"]["success"] = tt_server_ban_success
            results["teamtalk_server_ban"]["message"] = tt_server_ban_msg
            # Not raising exception on failure here as it's 'conceptual'
        else:
            results["teamtalk_server_ban"]["success"] = True  # Skipped
            results["teamtalk_server_ban"]["message"] = _("No TeamTalk username for server ban attempt.")

        # Commit ban changes before profile deletion
        if final_commit_needed:
            await session.commit()
            logger.debug("Committed ban list changes for user %s before profile deletion.", target_telegram_id)

        # Step 4: Delete user profile
        # This service function handles its own commits/rollbacks.
        profile_deleted_success = await user_service.delete_full_user_profile(
            session, target_telegram_id, services=services
        )
        results["profile_deletion"]["success"] = profile_deleted_success
        if profile_deleted_success:
            results["profile_deletion"]["message"] = _("Subscriber data also deleted.")
        else:
            results["profile_deletion"]["message"] = _("Error deleting subscriber data.")
            # This is a significant failure, but previous bans might have succeeded.
            # The overall success will be determined by the handler based on these results.

    except Exception:  # Covers SQLAlchemyError from helpers or explicit raises
        await session.rollback()
        logger.exception(
            "Error during ban and delete process for TG ID %s, triggering rollback.", target_telegram_id
        )
        # Update results to reflect failure if not already set by a specific step
        if not results["telegram_ban"]["message"] and not results["teamtalk_db_ban"]["message"]:
            # Generic error if no specific part failed before exception
            error_msg = _("Operation failed due to an internal error.")
            for key in results:  # noqa: PLC0206
                if results[key]["message"] is None:  # Don't overwrite specific error messages
                    results[key]["success"] = False
                    results[key]["message"] = error_msg
    return results


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

    # Determine the new value for not_on_online_enabled
    new_noon_enabled_value = not target_user_settings.not_on_online_enabled

    # Update the 'not_on_online_enabled' field
    updated_settings = await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=target_user_settings,
        field_name="not_on_online_enabled",
        new_value=new_noon_enabled_value,
        log_context=f" by admin for user {target_telegram_id} (toggle NOON)",
    )

    if not updated_settings:
        # Error occurred and was logged by _update_user_setting_field
        return None

    # If NOON was enabled and not yet confirmed, attempt to set not_on_online_confirmed to True
    if updated_settings.not_on_online_enabled and (updated_settings.not_on_online_confirmed is not True):
        confirmed_settings = await _utils._update_user_setting_field(
            session=session,
            services=services,
            settings_to_update=updated_settings,
            field_name="not_on_online_confirmed",
            new_value=True,
            log_context=f" by admin for user {target_telegram_id} (confirm NOON after toggle)",
        )
        if not confirmed_settings:
            # Log a warning if the confirmation step failed
            logger.warning(
                "NOON setting was toggled to enabled for user %s, "
                "but the subsequent confirmation of 'not_on_online_confirmed' failed. "
                "The 'not_on_online_enabled' field remains updated.",
                target_telegram_id,
            )
            return updated_settings  # Return the settings from the first successful update
        return confirmed_settings  # Both updates succeeded
    # Conditions for this path:
    # 1. NOON was toggled to False.
    # 2. NOON was toggled to True, but 'not_on_online_confirmed' was already True.
    # In these cases, the 'updated_settings' from the first call is the final state.
    return updated_settings


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

    return await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=target_user_settings,
        field_name="mute_list_mode",
        new_value=new_mode,
        log_context=" by admin",
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

    return await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=target_user_settings,
        field_name="notification_settings",
        new_value=new_pref_enum,
        log_context=f" by admin for user {target_telegram_id}",
    )


async def admin_link_tt_account(
    session: AsyncSession,
    services: "Services",
    target_telegram_id: int,
    tt_username_to_link: str,
) -> OperationResult:
    """Links a TeamTalk account to a subscriber, managed by an admin.

    Returns an OperationResult indicating success/failure and relevant details.
    """
    if await crud.is_teamtalk_username_banned(session, tt_username_to_link):
        logger.warning(
            "Attempt to link banned TeamTalk username '%s' to user %s.",
            tt_username_to_link,
            target_telegram_id,
        )
        return OperationResult(
            success=False, message_key="link_tt_account_error_banned", message_args={"tt_username": tt_username_to_link}
        )

    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        logger.warning("admin_link_tt_account: UserSettings not found for %s.", target_telegram_id)
        return OperationResult(success=False, message_key="link_tt_account_error_not_found")

    original_tt_username = target_user_settings.teamtalk_username

    # Update teamtalk_username
    updated_settings_tt_link = await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=target_user_settings,
        field_name="teamtalk_username",
        new_value=tt_username_to_link,
        log_context=f" by admin for user {target_telegram_id} (link TT account)",
    )

    if not updated_settings_tt_link:
        # Error already logged by helper _update_user_setting_field
        return OperationResult(success=False, message_key="link_tt_account_error_generic")

    # Determine message key based on whether it was a new link or a re-link
    is_relink = bool(original_tt_username and original_tt_username != tt_username_to_link)
    link_type_message_key_suffix = "relinked" if is_relink else "linked"
    success_message_key = f"link_tt_account_success_{link_type_message_key_suffix}"

    message_args = {
        "new_tt_username": tt_username_to_link,
        "original_tt_username": original_tt_username or "",  # Ensure not None for formatting
    }

    final_settings = updated_settings_tt_link
    # Ensure not_on_online_confirmed is set to True
    if updated_settings_tt_link.not_on_online_confirmed is not True:
        confirmed_settings = await _utils._update_user_setting_field(
            session=session,
            services=services,
            settings_to_update=updated_settings_tt_link,  # Use the already updated settings object
            field_name="not_on_online_confirmed",
            new_value=True,
            log_context=f" by admin for user {target_telegram_id} (confirm NOON for TT link)",
        )
        if not confirmed_settings:
            # Log a warning if the confirmation step failed, but the primary link operation was successful.
            # The overall operation is still considered a success regarding the link.
            logger.warning(
                "TT username '%s' linked for user %s, but failed to set not_on_online_confirmed to True.",
                tt_username_to_link,
                target_telegram_id,
            )
            # final_settings remains updated_settings_tt_link from the first successful update
        else:
            final_settings = confirmed_settings  # Both updates were successful

    return OperationResult(
        success=True, message_key=success_message_key, message_args=message_args, user_settings=final_settings
    )


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

    updated_settings = await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=target_user_settings,
        field_name="language_code",
        new_value=new_lang_code,
        log_context=" by admin",
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
