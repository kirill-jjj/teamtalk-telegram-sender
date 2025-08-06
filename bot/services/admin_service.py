"""Service layer for administrator-related operations."""

from collections.abc import Awaitable, Callable
from gettext import GNUTranslations
import logging
from typing import Any, Literal, TypeVar

from aiogram import Bot
import pytalk
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import Actor
from bot.database import crud
from bot.models import MuteListMode, NotificationSetting, OperationResult, UserSettings
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.connection import TeamTalkConnection

from . import _utils, user_service
from ._utils import managed_db_transaction

logger = logging.getLogger(__name__)


async def _add_or_remove_admin(
    session: AsyncSession,
    telegram_id: int,
    user_settings: UserSettings,
    cache: CacheService,
    bot: Bot,
    translator: GNUTranslations,
    action: Literal["add", "remove"],
) -> bool:
    """A generic helper to add or remove an admin, updating all necessary components."""
    try:
        if action == "add":
            db_success = await crud.add_admin(session, telegram_id)
            log_verb_past = "added"
            log_verb_present = "add"
            cache_op = cache.add_admin
        else:  # action == "remove"
            db_success = await crud.remove_admin_db(session, telegram_id)
            log_verb_past = "removed"
            log_verb_present = "remove"
            cache_op = cache.remove_admin

        if not db_success:
            logger.warning(
                "Failed to %s admin %s in DB (possibly due to state or DB error).", log_verb_present, telegram_id
            )
            return False

        logger.info("Admin %s %s to/from DB.", telegram_id, log_verb_past)
        cache_op(telegram_id)
        logger.info("Admin %s %s to/from cache.", telegram_id, log_verb_past)

        if user_settings:
            commands_updated = await _utils.update_user_bot_commands(
                telegram_id, user_settings.language_code, cache, bot, translator
            )
            if commands_updated:
                logger.info("Bot commands updated for admin %s following %s action.", telegram_id, action)
            else:
                logger.warning("Failed to update bot commands for admin %s.", telegram_id)
        else:
            logger.warning(
                "User settings not available for admin %s, commands not updated.",
                telegram_id,
            )

    except Exception:
        logger.exception("Error in _manage_admin_status for telegram_id %s, action '%s'.", telegram_id, action)
        return False
    else:
        return True


async def add_admin(
    session: AsyncSession,
    telegram_id: int,
    user_settings: UserSettings,
    cache: CacheService,
    bot: Bot,
    translator: GNUTranslations,
) -> bool:
    """Adds an admin to the DB, updates cache, and refreshes bot commands."""
    return await _add_or_remove_admin(session, telegram_id, user_settings, cache, bot, translator, action="add")


async def remove_admin(
    session: AsyncSession,
    telegram_id: int,
    user_settings: UserSettings,
    cache: CacheService,
    bot: Bot,
    translator: GNUTranslations,
) -> bool:
    """Removes an admin from the DB, updates cache, and refreshes bot commands."""
    return await _add_or_remove_admin(session, telegram_id, user_settings, cache, bot, translator, action="remove")


async def _ban_telegram_user(session: AsyncSession, target_telegram_id: int) -> bool:
    """Bans a Telegram ID. Returns True on success or if already banned, False on error."""
    async with managed_db_transaction(session, logger) as transaction_success:
        if not transaction_success:
            return False
        banned_tg = await crud.add_to_ban_list(
            session, telegram_id=target_telegram_id, reason="Banned by admin via subscriber menu"
        )
        if not banned_tg:
            logger.info("Telegram ID %s might already be banned or DB issue prevented re-ban.", target_telegram_id)
        return True


async def _ban_teamtalk_user_in_db(session: AsyncSession, tt_username: str, target_telegram_id: int) -> bool:
    """Bans a TeamTalk username in the database."""
    if not tt_username:
        logger.debug("No TeamTalk username provided to _ban_teamtalk_user_in_db for TG ID %s.", target_telegram_id)
        return True

    async with managed_db_transaction(session, logger) as transaction_success:
        if not transaction_success:
            return False
        banned_tt = await crud.add_to_ban_list(
            session,
            teamtalk_username=tt_username,
            reason=f"Banned by admin (linked to TG ID: {target_telegram_id})",
        )
        if not banned_tt:
            logger.info("TeamTalk username %s might already be banned or DB issue prevented re-ban.", tt_username)
        return True


async def _apply_server_moderation(
    action: Literal["ban", "unban"],
    tt_connection: "TeamTalkConnection | None",
    tt_username: str,
    target_telegram_id: int,
) -> bool:
    """Handles conceptual ban/unban on the TeamTalk server. Currently logs only."""
    if not tt_username:
        logger.debug(
            "No TeamTalk username for _manage_teamtalk_user_on_server(action=%s), TG ID %s.",
            action,
            target_telegram_id,
        )
        return True

    if tt_connection and tt_connection.instance and tt_connection.is_ready:
        try:
            logger.info(
                "Conceptual TT server %s attempt for username '%s' (linked to TG ID %s) on server %s. "
                "Actual server-side action by username not yet supported by SDK.",
                action,
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
        except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError):
            logger.exception(
                "Error during conceptual TeamTalk server %s for username '%s' (TG ID %s) on %s.",
                action,
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
            return False
        except Exception:
            logger.exception(
                "Unexpected error during conceptual TeamTalk server %s for username '%s' (TG ID %s) on %s.",
                action,
                tt_username,
                target_telegram_id,
                tt_connection.server_info.host,
            )
            return False
        else:
            return True
    else:
        logger.warning(
            "Skipping conceptual TeamTalk server %s for username '%s' (TG ID %s) as tt_connection "
            "or instance is None/invalid/not ready.",
            action,
            tt_username,
            target_telegram_id,
        )
        return True


async def _execute_ban(
    session: AsyncSession,
    target_telegram_id: int,
    tt_username_to_ban: str | None,
    tt_connection: "TeamTalkConnection | None",
) -> tuple[dict[str, bool], bool]:
    """Orchestrates banning a user's Telegram ID and TeamTalk username."""
    ban_statuses: dict[str, bool] = {
        "telegram_ban": False,
        "teamtalk_db_ban": False,
        "teamtalk_server_ban": False,
    }
    commit_needed_for_bans = False

    tg_ban_success = await _ban_telegram_user(session, target_telegram_id)
    ban_statuses["telegram_ban"] = tg_ban_success
    if not tg_ban_success:
        logger.error("Telegram ID ban failed for %s.", target_telegram_id)
    else:
        commit_needed_for_bans = True

    if tt_username_to_ban:
        tt_db_ban_success = await _ban_teamtalk_user_in_db(session, tt_username_to_ban, target_telegram_id)
        ban_statuses["teamtalk_db_ban"] = tt_db_ban_success
        if not tt_db_ban_success:
            logger.error("TeamTalk DB ban failed for username %s (TG ID %s).", tt_username_to_ban, target_telegram_id)
        else:
            commit_needed_for_bans = True
    else:
        ban_statuses["teamtalk_db_ban"] = True

    if tt_username_to_ban:
        tt_server_ban_success = await _apply_server_moderation(
            action="ban",
            tt_connection=tt_connection,
            tt_username=tt_username_to_ban,
            target_telegram_id=target_telegram_id,
        )
        ban_statuses["teamtalk_server_ban"] = tt_server_ban_success
        if not tt_server_ban_success:
            logger.warning(
                "Conceptual TeamTalk server ban failed or was skipped for username %s (TG ID %s).",
                tt_username_to_ban,
                target_telegram_id,
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
    """Bans a user's Telegram ID and TeamTalk username."""
    return await _execute_ban(session, target_telegram_id, tt_username_to_ban, tt_connection)


async def ban_and_delete_subscriber(
    session: AsyncSession,
    cache: CacheService,
    translator: GNUTranslations,
    target_telegram_id: int,
    tt_connection: "TeamTalkConnection | None",
) -> OperationResult:
    """Orchestrates the entire process of banning and deleting a subscriber."""
    user_settings = await session.get(UserSettings, target_telegram_id)
    tt_username_to_ban = user_settings.teamtalk_username if user_settings else None

    ban_statuses, commit_needed = await ban_user(session, target_telegram_id, tt_username_to_ban, tt_connection)

    profile_deleted_status = False
    if ban_statuses.get("telegram_ban"):
        if commit_needed:
            async with managed_db_transaction(session, logger):
                pass
        profile_deleted_status = await user_service.delete_user_profile(session, target_telegram_id, cache=cache)
    else:
        await session.rollback()

    return format_ban_result(
        translator=translator,
        telegram_id=target_telegram_id,
        tt_username=tt_username_to_ban,
        tg_banned=ban_statuses.get("telegram_ban", False),
        tt_db_banned=ban_statuses.get("teamtalk_db_ban", False),
        tt_server_banned=ban_statuses.get("teamtalk_server_ban", False),
        profile_deleted=profile_deleted_status,
    )


def format_ban_result(
    translator: GNUTranslations | None,
    telegram_id: int,
    tt_username: str | None,
    *,
    tg_banned: bool,
    tt_db_banned: bool,
    tt_server_banned: bool,
    profile_deleted: bool,
) -> OperationResult:
    """Formats a consolidated message based on the outcomes of ban and delete operations."""
    _ = translator.gettext if translator else lambda s: s
    parts = []

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
                _("✅ Conceptual TeamTalk server ban for {tt_username} was processed.").format(tt_username=tt_username)
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
    message_key = ""
    message_args = {"telegram_id": telegram_id, "tt_username": tt_username or ""}

    if fully_successful:
        message_key = "ban_success_full"
    elif tg_banned:
        message_key = "ban_partial_success"
    else:
        message_key = "ban_critical_failure"

    long_message_header = _("Banning process report for user {telegram_id}:").format(telegram_id=telegram_id)
    long_message = f"{long_message_header}\n\n" + "\n".join(parts)

    return OperationResult(
        success=fully_successful,
        message_key=message_key,
        message_args=message_args,
        long_message=long_message,
    )


T = TypeVar("T")
UpdateFunc = Callable[..., Awaitable[T | None]]


async def _admin_update_user_setting(
    session: AsyncSession,
    cache: CacheService,
    bot: Bot,
    translator: GNUTranslations,
    target_telegram_id: int,
    update_function: UpdateFunc,
    **kwargs: Any,
) -> T | None:
    """Generic helper to update a user setting for a target user by an admin."""
    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        logger.warning(
            "%s: UserSettings not found for %s",
            update_function.__name__,
            target_telegram_id,
        )
        return None

    kwargs["actor"] = Actor.ADMIN
    return await update_function(
        session=session,
        cache=cache,
        bot=bot,
        translator=translator,
        user_settings=target_user_settings,
        **kwargs,
    )


async def admin_toggle_noon_setting(
    session: AsyncSession,
    cache: CacheService,
    bot: Bot,
    translator: GNUTranslations,
    target_telegram_id: int,
) -> UserSettings | None:
    """Toggles the NOON (Not On Online Notifications) setting for a target user."""
    return await _admin_update_user_setting(
        session, cache, bot, translator, target_telegram_id, user_service.update_noon_setting
    )


async def admin_set_user_mute_mode(
    session: AsyncSession,
    cache: CacheService,
    bot: Bot,
    translator: GNUTranslations,
    target_telegram_id: int,
    new_mode: "MuteListMode",
) -> UserSettings | None:
    """Sets the mute list mode for a target user, managed by an admin."""
    return await _admin_update_user_setting(
        session, cache, bot, translator, target_telegram_id, user_service.update_mute_mode, new_mode=new_mode
    )


async def admin_set_user_notification_preference(
    session: AsyncSession,
    cache: CacheService,
    bot: Bot,
    translator: GNUTranslations,
    target_telegram_id: int,
    new_pref_enum: "NotificationSetting",
) -> UserSettings | None:
    """Sets the notification preference for a target user, managed by an admin."""
    return await _admin_update_user_setting(
        session,
        cache,
        bot,
        translator,
        target_telegram_id,
        user_service.update_notification_preference,
        new_pref=new_pref_enum,
    )


async def admin_link_tt_account(
    session: AsyncSession,
    cache: CacheService,
    target_telegram_id: int,
    tt_username_to_link: str,
    translator: "GNUTranslations",
) -> OperationResult:
    """Links a TeamTalk account to a subscriber, managed by an admin."""
    _ = translator.gettext
    if await crud.is_teamtalk_username_banned(session, tt_username_to_link):
        logger.warning(
            "Attempt to link banned TeamTalk username '%s' to user %s.",
            tt_username_to_link,
            target_telegram_id,
        )
        return OperationResult(
            success=False,
            message_key=_("link_tt_account_error_banned"),
            message_args={"tt_username": tt_username_to_link},
        )

    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        logger.warning("admin_link_tt_account: UserSettings not found for %s.", target_telegram_id)
        return OperationResult(success=False, message_key=_("link_tt_account_error_not_found"))

    original_tt_username = target_user_settings.teamtalk_username

    updated_settings_tt_link = await _utils._update_user_setting_field(
        session=session,
        cache=cache,
        settings_to_update=target_user_settings,
        field_name="teamtalk_username",
        new_value=tt_username_to_link,
        log_context=f" by admin for user {target_telegram_id} (link TT account)",
    )

    if not updated_settings_tt_link:
        return OperationResult(success=False, message_key=_("link_tt_account_error_generic"))

    is_relink = bool(original_tt_username and original_tt_username != tt_username_to_link)
    success_message_key = _("link_tt_account_success_relinked") if is_relink else _("link_tt_account_success_linked")
    message_args = {
        "new_tt_username": tt_username_to_link,
        "original_tt_username": original_tt_username or "",
    }

    final_settings = updated_settings_tt_link
    if updated_settings_tt_link.not_on_online_confirmed is not True:
        confirmed_settings = await _utils._update_user_setting_field(
            session=session,
            cache=cache,
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
    tt_connection: "TeamTalkConnection | None",
    target_telegram_id: int,
) -> OperationResult:
    """Unbans a subscriber by removing all their ban entries."""
    async with managed_db_transaction(session, logger) as transaction_success:
        if not transaction_success:
            return OperationResult(
                success=False,
                message_key="unban_error_generic",
                message_args={"telegram_id": target_telegram_id},
            )

        user_settings = await session.get(UserSettings, target_telegram_id)
        tt_username = user_settings.teamtalk_username if user_settings else None

        db_unban_success = await crud.remove_ban_entries_for_telegram_id(session, target_telegram_id)
        tt_unban_success = True
        if tt_username:
            tt_unban_success = await _apply_server_moderation(
                action="unban",
                tt_connection=tt_connection,
                tt_username=tt_username,
                target_telegram_id=target_telegram_id,
            )

        if db_unban_success and tt_unban_success:
            logger.info("Successfully unbanned user %s.", target_telegram_id)
            return OperationResult(
                success=True,
                message_key="unban_success",
                message_args={"telegram_id": target_telegram_id},
            )
        logger.error("Failed to unban user %s.", target_telegram_id)
        return OperationResult(
            success=False,
            message_key="unban_error_failed",
            message_args={"telegram_id": target_telegram_id},
        )


async def admin_set_user_language(
    session: AsyncSession,
    cache: CacheService,
    bot: Bot,
    translator: GNUTranslations,
    target_telegram_id: int,
    new_lang_code: str,
) -> UserSettings | None:
    """Sets the language for a target user, managed by an admin."""
    return await _admin_update_user_setting(
        session,
        cache,
        bot,
        translator,
        target_telegram_id,
        user_service.update_language,
        new_lang_code=new_lang_code,
    )
