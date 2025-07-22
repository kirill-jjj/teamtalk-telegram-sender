"""Service layer for administrator-related operations."""

import gettext
import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database import crud
from bot.models import MuteListMode, NotificationSetting, OperationResult, UserSettings

from . import _utils, user_service

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


async def _ban_telegram_user(session: AsyncSession, target_telegram_id: int) -> bool:
    """Bans a Telegram ID. Returns True on success or if already banned, False on error."""
    try:
        banned_tg = await crud.add_to_ban_list(
            session, telegram_id=target_telegram_id, reason="Banned by admin via subscriber menu"
        )
        if not banned_tg:
            # If not banned_tg, it means already banned or some other non-exception failure from crud
            logger.info("Telegram ID %s might already be banned or DB issue prevented re-ban.", target_telegram_id)
    except SQLAlchemyError:
        logger.exception("SQLAlchemyError while banning Telegram ID %s.", target_telegram_id)
        return False
    except Exception:
        logger.exception("Unexpected error while banning Telegram ID %s.", target_telegram_id)
        return False
    else:
        return True


async def _ban_teamtalk_user_in_db(session: AsyncSession, tt_username: str, target_telegram_id: int) -> bool:
    """Bans a TeamTalk username in the database.

    Returns True on success or if already banned, False on error.
    """
    if not tt_username:
        logger.debug("No TeamTalk username provided to _ban_teamtalk_user_in_db for TG ID %s.", target_telegram_id)
        return True  # No username to ban, not an error for this specific function

    try:
        banned_tt = await crud.add_to_ban_list(
            session,
            teamtalk_username=tt_username,
            reason=f"Banned by admin (linked to TG ID: {target_telegram_id})",
        )
        if not banned_tt:
            logger.info("TeamTalk username %s might already be banned or DB issue prevented re-ban.", tt_username)
    except SQLAlchemyError:
        logger.exception("SQLAlchemyError while banning TeamTalk username %s in DB.", tt_username)
        return False
    except Exception:
        logger.exception("Unexpected error while banning TeamTalk username %s in DB.", tt_username)
        return False
    else:
        return True


async def _ban_teamtalk_user_on_server(
    tt_connection: "TeamTalkConnection | None",
    tt_username: str,
    target_telegram_id: int,  # For logging context
) -> bool:
    """Attempts a conceptual ban on the TeamTalk server. Currently logs only.

    Returns True if successful (or skipped), False on error.
    """
    if not tt_username:
        logger.debug("No TeamTalk username provided to _ban_teamtalk_user_on_server for TG ID %s.", target_telegram_id)
        return True  # No username, nothing to do on server

    if tt_connection and tt_connection.instance and tt_connection.is_ready:
        try:
            # Placeholder for actual ban logic
            logger.info(
                "Conceptual TT server ban attempt for username '%s' (linked to TG ID %s) on server %s. "
                "Actual server-side ban by username not yet supported by SDK.",
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
        except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError):
            logger.exception(
                "Error during conceptual TeamTalk server ban for username '%s' (TG ID %s) on %s.",
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
            return False
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Unexpected error during conceptual TeamTalk server ban for username '%s' (TG ID %s) on %s.",
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
            return False
        else:
            return True
    else:
        logger.warning(
            "Skipping conceptual TeamTalk server ban for username '%s' (TG ID %s) as tt_connection "
            "or instance is None/invalid/not ready.",
            tt_username,
            target_telegram_id,
        )
        return True # Skipped is not an error for this conceptual ban


async def _unban_teamtalk_user_on_server(
    tt_connection: "TeamTalkConnection | None",
    tt_username: str,
    target_telegram_id: int,
) -> bool:
    """Attempts a conceptual unban on the TeamTalk server. Currently logs only."""
    if not tt_username:
        logger.debug(
            "No TeamTalk username for _unban_teamtalk_user_on_server, TG ID %s.", target_telegram_id
        )
        return True

    if tt_connection and tt_connection.instance and tt_connection.is_ready:
        try:
            logger.info(
                "Conceptual TT server unban attempt for username '%s' (linked to TG ID %s) on server %s. "
                "Actual server-side unban by username not yet supported by SDK.",
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
        except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError):
            logger.exception(
                "Error during conceptual TeamTalk server unban for username '%s' (TG ID %s) on %s.",
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
            return False
        except Exception:
            logger.exception(
                "Unexpected error during conceptual TeamTalk server unban for username '%s' (TG ID %s) on %s.",
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
            return False
        else:
            return True
    else:
        logger.warning(
            "Skipping conceptual TeamTalk server unban for username '%s' (TG ID %s) as tt_connection "
            "or instance is None/invalid/not ready.",
            tt_username,
            target_telegram_id,
        )
        return True


async def _orchestrate_user_banning(
    session: AsyncSession,
    target_telegram_id: int,
    tt_username_to_ban: str | None,
    tt_connection: "TeamTalkConnection | None",
) -> tuple[dict[str, bool], bool]:
    """Orchestrates banning a user's Telegram ID and TeamTalk username.

    Handles banning in the database and conceptually on the TeamTalk server.
    Returns a dictionary of success statuses and a boolean indicating if a commit is needed.
    """
    ban_statuses: dict[str, bool] = {
        "telegram_ban": False,
        "teamtalk_db_ban": False,
        "teamtalk_server_ban": False,
    }
    commit_needed_for_bans = False

    # Step 1: Ban Telegram ID
    tg_ban_success = await _ban_telegram_user(session, target_telegram_id)
    ban_statuses["telegram_ban"] = tg_ban_success
    if not tg_ban_success:
        logger.error("Telegram ID ban failed for %s.", target_telegram_id)
    else:
        commit_needed_for_bans = True

    # Step 2: Ban TeamTalk username in DB (if exists)
    if tt_username_to_ban:
        tt_db_ban_success = await _ban_teamtalk_user_in_db(
            session, tt_username_to_ban, target_telegram_id
        )
        ban_statuses["teamtalk_db_ban"] = tt_db_ban_success
        if not tt_db_ban_success:
            logger.error("TeamTalk DB ban failed for username %s (TG ID %s).", tt_username_to_ban, target_telegram_id)
        else:
            commit_needed_for_bans = True
    else:
        ban_statuses["teamtalk_db_ban"] = True

    # Step 3: Conceptual TeamTalk server ban (if TT username exists)
    if tt_username_to_ban:
        tt_server_ban_success = await _ban_teamtalk_user_on_server(
            tt_connection, tt_username_to_ban, target_telegram_id
        )
        ban_statuses["teamtalk_server_ban"] = tt_server_ban_success
        if not tt_server_ban_success:
            logger.warning(
                "Conceptual TeamTalk server ban failed or was skipped for username %s (TG ID %s).",
                 tt_username_to_ban,
                 target_telegram_id
            )
    else:
        ban_statuses["teamtalk_server_ban"] = True

    return ban_statuses, commit_needed_for_bans


async def ban_user(
    session: AsyncSession,
    target_telegram_id: int,
    tt_username_to_ban: str | None,
    tt_connection: "TeamTalkConnection | None",
) -> tuple[dict[str, bool], bool]:
    """Bans a user's Telegram ID and TeamTalk username.

    Handles banning in the database and conceptually on the TeamTalk server.
    Returns a dictionary of success statuses and a boolean indicating if a commit is needed.
    """
    return await _orchestrate_user_banning(
        session, target_telegram_id, tt_username_to_ban, tt_connection
    )


async def ban_and_delete_subscriber(
    session: AsyncSession,
    services: "Services",
    target_telegram_id: int,
    tt_connection: "TeamTalkConnection | None",
) -> tuple[str, str]:
    """Orchestrates the entire process of banning and deleting a subscriber.

    This function will:
    1. Fetch the user's TeamTalk username.
    2. Call the ban_user service function.
    3. If the Telegram ban is successful, commit the transaction.
    4. Call the user_service to delete the user's profile.
    5. Format and return the result messages.
    """
    user_settings = await session.get(UserSettings, target_telegram_id)
    tt_username_to_ban = user_settings.teamtalk_username if user_settings else None

    ban_statuses, commit_needed = await ban_user(
        session, target_telegram_id, tt_username_to_ban, tt_connection
    )

    profile_deleted_status = False
    if ban_statuses.get("telegram_ban"):
        if commit_needed:
            await session.commit()
        profile_deleted_status = await user_service.delete_full_user_profile(
            session, target_telegram_id, services=services
        )
    else:
        await session.rollback()

    translator = services.get_translator()
    if not isinstance(translator, gettext.GNUTranslations):
        # Fallback to a default translator if a specific one isn't found
        translator = services.get_translator(services.config.general.default_lang)

    return format_ban_delete_result_message(
        translator=translator,
        telegram_id=target_telegram_id,
        tt_username=tt_username_to_ban,
        tg_banned=ban_statuses.get("telegram_ban", False),
        tt_db_banned=ban_statuses.get("teamtalk_db_ban", False),
        tt_server_banned=ban_statuses.get("teamtalk_server_ban", False),
        profile_deleted=profile_deleted_status,
    )


def format_ban_delete_result_message(  # noqa: PLR0912
    translator: gettext.GNUTranslations | gettext.NullTranslations,
    telegram_id: int,
    tt_username: str | None,
    *,
    tg_banned: bool,
    tt_db_banned: bool,
    tt_server_banned: bool,
    profile_deleted: bool,
) -> tuple[str, str]:
    """Formats a consolidated message based on the outcomes of ban and delete operations."""
    _ = translator.gettext
    parts = []
    short_message = ""

    if tg_banned:
        parts.append(_("✅ Telegram ID {telegram_id} has been banned.").format(telegram_id=telegram_id))
    else:
        parts.append(_("❌ Failed to ban Telegram ID {telegram_id}.").format(telegram_id=telegram_id))

    if tt_username:
        if tt_db_banned:
            parts.append(
                _("✅ TeamTalk username {tt_username} has been banned in the database.").format(tt_username=tt_username)
            )
        else:
            parts.append(
                _("❌ Failed to ban TeamTalk username {tt_username} in the database.").format(tt_username=tt_username)
            )

        if tt_server_banned:
            parts.append(
                _("✅ Conceptual TeamTalk server ban for {tt_username} was processed.").format(
                    tt_username=tt_username
                )
            )
        else:
            parts.append(
                _("⚠️ Conceptual TeamTalk server ban for {tt_username} encountered an issue.").format(
                    tt_username=tt_username
                )
            )
    else:
        parts.append(_("ℹ️ No TeamTalk username was linked; TeamTalk ban steps skipped."))

    if tg_banned:
        if profile_deleted:
            parts.append(_("✅ User profile and data have been deleted."))
        else:
            parts.append(_("❌ Failed to delete user profile and data after banning."))
    else:
        parts.append(_("ℹ️ User profile deletion was skipped due to Telegram ban failure."))

    fully_successful = tg_banned and (tt_db_banned if tt_username else True) and profile_deleted

    if fully_successful:
        short_message = _("User {telegram_id} banned successfully.").format(telegram_id=telegram_id)
        if tt_username:
            short_message += _(" TT: {tt_username}").format(tt_username=tt_username)
    elif tg_banned:
        short_message = _("Partial success banning user {telegram_id}. Check details.").format(telegram_id=telegram_id)
    else:
        short_message = _("CRITICAL: Failed to ban Telegram ID {telegram_id}.").format(telegram_id=telegram_id)

    long_message_header = _("Banning process report for user {telegram_id}:").format(telegram_id=telegram_id)
    long_message = f"{long_message_header}\n\n" + "\n".join(parts)

    return short_message, long_message


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

    new_noon_enabled_value = not target_user_settings.not_on_online_enabled

    updated_settings = await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=target_user_settings,
        field_name="not_on_online_enabled",
        new_value=new_noon_enabled_value,
        log_context=f" by admin for user {target_telegram_id} (toggle NOON)",
    )

    if not updated_settings:
        return None

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
            logger.warning(
                "NOON setting was toggled to enabled for user %s, "
                "but the subsequent confirmation of 'not_on_online_confirmed' failed. "
                "The 'not_on_online_enabled' field remains updated.",
                target_telegram_id,
            )
            return updated_settings
        return confirmed_settings
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

    updated_settings_tt_link = await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=target_user_settings,
        field_name="teamtalk_username",
        new_value=tt_username_to_link,
        log_context=f" by admin for user {target_telegram_id} (link TT account)",
    )

    if not updated_settings_tt_link:
        return OperationResult(success=False, message_key="link_tt_account_error_generic")

    is_relink = bool(original_tt_username and original_tt_username != tt_username_to_link)
    link_type_message_key_suffix = "relinked" if is_relink else "linked"
    success_message_key = f"link_tt_account_success_{link_type_message_key_suffix}"

    message_args = {
        "new_tt_username": tt_username_to_link,
        "original_tt_username": original_tt_username or "",
    }

    final_settings = updated_settings_tt_link
    if updated_settings_tt_link.not_on_online_confirmed is not True:
        confirmed_settings = await _utils._update_user_setting_field(
            session=session,
            services=services,
            settings_to_update=updated_settings_tt_link,
            field_name="not_on_online_confirmed",
            new_value=True,
            log_context=f" by admin for user {target_telegram_id} (confirm NOON for TT link)",
        )
        if not confirmed_settings:
            logger.warning(
                "TT username '%s' linked for user %s, but failed to set not_on_online_confirmed to True.",
                tt_username_to_link,
                target_telegram_id,
            )
        else:
            final_settings = confirmed_settings

    return OperationResult(
        success=True, message_key=success_message_key, message_args=message_args, user_settings=final_settings
    )


async def unban_subscriber(
    session: AsyncSession,
    _services: "Services",
    tt_connection: "TeamTalkConnection | None",
    target_telegram_id: int,
    translator: "gettext.GNUTranslations",
) -> str:
    """Unbans a subscriber by removing all their ban entries."""
    _ = translator.gettext
    try:
        user_settings = await session.get(UserSettings, target_telegram_id)
        tt_username = user_settings.teamtalk_username if user_settings else None

        db_unban_success = await crud.remove_ban_entries_for_telegram_id(session, target_telegram_id)
        tt_unban_success = True
        if tt_username:
            tt_unban_success = await _unban_teamtalk_user_on_server(
                tt_connection, tt_username, target_telegram_id
            )

        if db_unban_success and tt_unban_success:
            logger.info("Successfully unbanned user %s.", target_telegram_id)
            return _("User {telegram_id} has been unbanned.").format(telegram_id=target_telegram_id)
        logger.error("Failed to unban user %s.", target_telegram_id)
        return _("Failed to unban user {telegram_id}.").format(telegram_id=target_telegram_id)
    except Exception:
        logger.exception("An unexpected error occurred while unbanning user %s.", target_telegram_id)
        return _("An unexpected error occurred while unbanning user {telegram_id}.").format(
            telegram_id=target_telegram_id
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
