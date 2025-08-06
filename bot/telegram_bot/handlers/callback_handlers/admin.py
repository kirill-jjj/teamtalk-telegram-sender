"""Callback query handlers for administrator actions originating from inline keyboards."""

from gettext import NullTranslations
from html import escape
import logging
from typing import Annotated

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka
import pytalk
from pytalk.exceptions import PermissionError as PytalkPermissionError
from pytalk.exceptions import TeamTalkException as PytalkException

from bot.core.enums import AdminCommand
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.utils import get_tt_user_display_name
from bot.telegram_bot.callback_data import AdminCallback

from ._helpers import ensure_message_context, ensure_tt_user_exists, safe_edit_text

logger = logging.getLogger(__name__)
admin_actions_router = Router(name="callback_handlers.admin")

ttstr = pytalk.instance.sdk.ttstr


def _handle_pytalk_error(
    exc: Exception,
    action: AdminCommand,
    user_id_to_log: int | str,
    server_host: str,
    translator: NullTranslations,
    *,
    is_critical: bool = False,
) -> tuple[bool, str]:
    """Handles common exceptions for Pytalk actions, logs, and returns a standardized error tuple."""
    _ = translator.gettext
    log_message = "Error during '%s' on TT user (ID: %s) on server %s."
    if is_critical:
        logger.critical(
            "CRITICAL: Network/OS error during '%s' on TT user (ID: %s) on server %s: %s",
            action,
            user_id_to_log,
            server_host,
            exc,
            exc_info=True,
        )
    else:
        logger.exception(log_message, action, user_id_to_log, server_host)

    return False, _("An error occurred. Please try again later.")


async def _apply_user_moderation(
    action: AdminCommand,
    user_to_act_on: pytalk.user.User,
    translator: NullTranslations,
    admin_tg_id: int,
    server_host: str,
) -> tuple[bool, str]:
    """Executes a moderation action on a TeamTalk user, returning the result."""
    _ = translator.gettext
    user_nickname = get_tt_user_display_name(user_to_act_on, translator)
    quoted_nickname = escape(user_nickname)
    success = False
    message = ""

    try:
        if action == AdminCommand.KICK:
            user_to_act_on.kick(from_server=True)
            logger.info(
                "Admin %s kicked TT user '%s' (ID: %s) from server %s",
                admin_tg_id,
                user_nickname,
                user_to_act_on.id,
                server_host,
            )
            success = True
            message = _("User {user_nickname} kicked from server {server_host}.").format(
                user_nickname=quoted_nickname, server_host=server_host
            )
        elif action == AdminCommand.BAN:
            user_to_act_on.ban(from_server=True)
            user_to_act_on.kick(from_server=True)
            logger.info(
                "Admin %s banned and kicked TT user '%s' (ID: %s) from server %s",
                admin_tg_id,
                user_nickname,
                user_to_act_on.id,
                server_host,
            )
            success = True
            message = _("User {user_nickname} banned and kicked from server {server_host}.").format(
                user_nickname=quoted_nickname, server_host=server_host
            )
        else:
            logger.warning("Unknown action '%s' passed to _execute_tt_user_action for server %s.", action, server_host)
            success = False
            message = _("Unknown action.")

    except PytalkPermissionError as e:
        success, message = _handle_pytalk_error(e, action, user_to_act_on.id, server_host, translator)
    except PytalkException as e:
        success, message = _handle_pytalk_error(e, action, user_to_act_on.id, server_host, translator)
    except (ValueError, TypeError, AttributeError) as e:
        user_id_log = user_to_act_on.id if hasattr(user_to_act_on, "id") else "UNKNOWN"
        success, message = _handle_pytalk_error(e, action, user_id_log, server_host, translator)
    except (TimeoutError, OSError) as e:
        user_id_log = user_to_act_on.id if hasattr(user_to_act_on, "id") else "UNKNOWN"
        success, message = _handle_pytalk_error(e, action, user_id_log, server_host, translator, is_critical=True)

    return success, message


@admin_actions_router.callback_query(AdminCallback.filter(F.action.in_({AdminCommand.KICK, AdminCommand.BAN})))
@ensure_message_context
@ensure_tt_user_exists
async def on_moderation_confirm(
    callback_query: CallbackQuery,
    callback_data: AdminCallback,
    translator: Annotated[NullTranslations, FromDishka()],
    tt_connection: TeamTalkConnection,
    tt_user: pytalk.user.User,
) -> None:
    """Processes admin actions (kick/ban) selected from an inline keyboard."""
    _ = translator.gettext
    server_host_for_display = tt_connection.server_info.host

    success, message_text = await _apply_user_moderation(
        action=callback_data.action,
        user_to_act_on=tt_user,
        translator=translator,
        admin_tg_id=callback_query.from_user.id,
        server_host=server_host_for_display,
    )

    if success:
        await callback_query.answer(_("Success!"), show_alert=False)
        await safe_edit_text(
            message_to_edit=callback_query.message,  # type: ignore[arg-type]
            text=message_text,
            reply_markup=None,
            logger_instance=logger,
            log_context=f"process_user_action_selection ({callback_data.action.value}) on {server_host_for_display}",
        )
    else:
        await callback_query.answer(message_text, show_alert=True)
