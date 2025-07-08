"""Callback query handlers for administrator actions originating from inline keyboards."""

import gettext
from html import escape
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
import pytalk
from pytalk.exceptions import PermissionError as PytalkPermissionError
from pytalk.exceptions import TeamTalkException as PytalkException

from bot.core.enums import AdminAction
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.utils import get_tt_user_display_name  # Updated import
from bot.telegram_bot.callback_data import AdminActionCallback

# Middlewares to apply
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
admin_actions_router = Router(name="callback_handlers.admin")
admin_actions_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
admin_actions_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())

ttstr = pytalk.instance.sdk.ttstr


async def _execute_tt_user_action(  # noqa: PLR0911
    action: AdminAction,
    user_to_act_on: pytalk.user.User,
    translator: gettext.GNUTranslations,
    admin_tg_id: int,
    server_host: str,
) -> tuple[bool, str]:
    """Executes a moderation action on a TeamTalk user.

    Returns a tuple of (success_boolean, message_string).
    """
    _ = translator.gettext
    user_nickname = get_tt_user_display_name(user_to_act_on, translator)
    quoted_nickname = escape(user_nickname)

    try:
        if action == AdminAction.KICK:
            user_to_act_on.kick(from_server=True)
            logger.info(
                "Admin %s kicked TT user '%s' (ID: %s) from server %s",
                admin_tg_id,
                user_nickname,
                user_to_act_on.id,
                server_host,
            )
            return True, _("User {user_nickname} kicked from server {server_host}.").format(
                user_nickname=quoted_nickname, server_host=server_host
            )
        elif action == AdminAction.BAN:
            user_to_act_on.ban(from_server=True)
            user_to_act_on.kick(from_server=True)
            logger.info(
                "Admin %s banned and kicked TT user '%s' (ID: %s) from server %s",
                admin_tg_id,
                user_nickname,
                user_to_act_on.id,
                server_host,
            )
            return True, _("User {user_nickname} banned and kicked from server {server_host}.").format(
                user_nickname=quoted_nickname, server_host=server_host
            )
        else:
            logger.warning("Unknown action '%s' passed to _execute_tt_user_action for server %s.", action, server_host)
            return False, _("Unknown action.")

    except PytalkPermissionError as e:
        logger.error(
            "PermissionError during '%s' on TT user ID %s on server %s: %s",
            action,
            user_to_act_on.id,
            server_host,
            e,
        )
        return False, _(
            "An error occurred while performing the action on server {server_host}. Please try again later."
        ).format(server_host=server_host)
    except PytalkException as e:
        logger.error(
            "TeamTalkException during '%s' on TT user ID %s on server %s: %s",
            action,
            user_to_act_on.id,
            server_host,
            e,
        )
        return False, _(
            "An error occurred while performing the action on server {server_host}. Please try again later."
        ).format(server_host=server_host)
    except (ValueError, TypeError, AttributeError) as e_data:
        user_id_log = user_to_act_on.id if hasattr(user_to_act_on, "id") else "UNKNOWN"
        logger.exception(
            "Data error during '%s' on TT user (ID: %s) on server %s: %s",
            action,
            user_id_log,
            server_host,
            e_data,
        )
        return False, _(
            "An error occurred while performing the action on server {server_host}. Please try again later."
        ).format(server_host=server_host)
    except (TimeoutError, OSError) as e_net:
        user_id_log = user_to_act_on.id if hasattr(user_to_act_on, "id") else "UNKNOWN"
        # For critical errors, logger.critical with exc_info=True is appropriate if not using .exception
        logger.critical(
            "CRITICAL: Network/OS error during '%s' on TT user (ID: %s) on server %s: %s",
            action,
            user_id_log,
            server_host,
            e_net,
            # Retaining exc_info for critical, as .exception might not be semantically identical to critical
            exc_info=True,
        )
        return False, _(
            "An error occurred while performing the action on server {server_host}. Please try again later."
        ).format(server_host=server_host)


@admin_actions_router.callback_query(AdminActionCallback.filter(F.action.in_({AdminAction.KICK, AdminAction.BAN})))
async def process_user_action_selection(
    callback_query: CallbackQuery,
    callback_data: AdminActionCallback,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    services: "Services",  # Injected from workflow_data
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
):
    """Processes admin actions (kick/ban) selected from an inline keyboard."""
    _ = translator.gettext
    if not callback_query.message:
        await callback_query.answer(_("Error: Message context not found."), show_alert=True)
        return

    if not services.cache.is_admin(callback_query.from_user.id):
        await callback_query.answer(_("You are not authorized for this action."), show_alert=True)
        return

    # TeamTalkConnectionCheckMiddleware (applied to router) ensures tt_connection and instance are valid
    if not tt_connection or not tt_connection.instance:
        # This check is somewhat redundant if TeamTalkConnectionCheckMiddleware is effective
        await callback_query.answer(_("TeamTalk connection is not available. Please try again later."), show_alert=True)
        return

    tt_instance = tt_connection.instance
    server_host_for_display = tt_connection.server_info.host

    user_to_act_on = tt_instance.get_user(callback_data.user_id)
    if not user_to_act_on:
        await callback_query.answer(
            _("User not found on server {server_host} anymore.").format(server_host=server_host_for_display),
            show_alert=True,
        )
        try:
            if callback_query.message:
                await callback_query.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            logger.debug(
                "Failed to remove reply markup when user %s was not found on %s.",
                callback_data.user_id,
                server_host_for_display,
            )
        return

    success, message_text = await _execute_tt_user_action(
        action=callback_data.action,
        user_to_act_on=user_to_act_on,
        translator=translator,
        admin_tg_id=callback_query.from_user.id,
        server_host=server_host_for_display,
    )

    if success:
        await callback_query.answer(_("Success!"), show_alert=False)
        if callback_query.message:
            try:
                await callback_query.message.edit_text(message_text, reply_markup=None)
            except TelegramAPIError as e:
                logger.warning(
                    "Failed to edit message text after user action on %s: %s. Trying to edit reply markup only.",
                    server_host_for_display,
                    e,
                )
                try:
                    await callback_query.message.edit_reply_markup(reply_markup=None)
                except TelegramAPIError as e_markup:
                    logger.error(
                        "Failed to even remove reply markup after user action on %s: %s",
                        server_host_for_display,
                        e_markup,
                    )
    else:
        await callback_query.answer(message_text, show_alert=True)
