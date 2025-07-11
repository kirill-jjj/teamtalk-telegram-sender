"""Callback query handlers for administrator actions originating from inline keyboards."""

import gettext
from html import escape
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
import pytalk
from pytalk.exceptions import PermissionError as PytalkPermissionError
from pytalk.exceptions import TeamTalkException as PytalkException

from bot.core.enums import AdminAction
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.utils import get_tt_user_display_name
from bot.telegram_bot.callback_data import AdminActionCallback

# Middlewares to apply
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware

from ._helpers import ensure_message_context, safe_edit_text

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
admin_actions_router = Router(name="callback_handlers.admin")
admin_actions_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
admin_actions_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())

ttstr = pytalk.instance.sdk.ttstr


def _handle_pytalk_action_error(
    exc: Exception,
    action: AdminAction,
    user_id_to_log: int | str,
    server_host: str,
    translator: gettext.GNUTranslations,
    *,
    is_critical: bool = False,
) -> tuple[bool, str]:
    """Handles common exceptions for Pytalk actions, logs, and returns a standardized error tuple."""
    _ = translator.gettext
    log_message = "Error during '%s' on TT user (ID: %s) on server %s."
    if is_critical:
        # For critical errors, logger.critical with exc_info=True is appropriate
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

    return False, _(
        "An error occurred while performing the action on server {server_host}. Please try again later."
    ).format(server_host=server_host)


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
        if action == AdminAction.BAN:
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
        logger.warning("Unknown action '%s' passed to _execute_tt_user_action for server %s.", action, server_host)
        return False, _("Unknown action.")

    except PytalkPermissionError as e:
        return _handle_pytalk_action_error(e, action, user_to_act_on.id, server_host, translator)
    except PytalkException as e:
        return _handle_pytalk_action_error(e, action, user_to_act_on.id, server_host, translator)
    except (ValueError, TypeError, AttributeError) as e:
        user_id_log = user_to_act_on.id if hasattr(user_to_act_on, "id") else "UNKNOWN"
        return _handle_pytalk_action_error(e, action, user_id_log, server_host, translator)
    except (TimeoutError, OSError) as e:
        user_id_log = user_to_act_on.id if hasattr(user_to_act_on, "id") else "UNKNOWN"
        return _handle_pytalk_action_error(e, action, user_id_log, server_host, translator, is_critical=True)


@admin_actions_router.callback_query(AdminActionCallback.filter(F.action.in_({AdminAction.KICK, AdminAction.BAN})))
@ensure_message_context
async def process_user_action_selection(
    callback_query: CallbackQuery,
    callback_data: AdminActionCallback,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
) -> None:
    """Processes admin actions (kick/ban) selected from an inline keyboard."""
    _ = translator.gettext
    # Decorator ensures callback_query.message exists.

    # Note: AdminCheckMiddleware is NOT on this specific callback router (admin_actions_router).
    # This task focuses on the TT connection check redundancy.

    # TeamTalkConnectionCheckMiddleware (applied to router) ensures tt_connection is valid and ready.
    # The manual check 'if not tt_connection or not tt_connection.instance:' is removed.
    # tt_connection is type hinted as TeamTalkConnection | None from ActiveTeamTalkConnectionMiddleware.
    # TeamTalkConnectionCheckMiddleware should prevent execution if it's None or not ready.

    tt_instance = tt_connection.instance  # type: ignore[union-attr] # Middleware ensures tt_connection is not None here
    server_host_for_display = tt_connection.server_info.host  # type: ignore[union-attr]

    user_to_act_on = tt_instance.get_user(callback_data.user_id)  # type: ignore[union-attr] # Middleware ensures tt_instance is not None
    if not user_to_act_on:
        await callback_query.answer(
            _("User not found on server {server_host} anymore.").format(server_host=server_host_for_display),
            show_alert=True,
        )
        try:
            if isinstance(callback_query.message, Message):
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
        # The @ensure_message_context decorator guarantees callback_query.message is a Message object.
        # No need for `isinstance(callback_query.message, Message)` check here.
        # We use safe_edit_text from the local _helpers module (which should be ui_utils.safe_edit_text)
        # to set the new text and remove the keyboard.
        await safe_edit_text(
            message_to_edit=callback_query.message,  # type: ignore[arg-type] # Decorator ensures this
            text=message_text,
            reply_markup=None,  # This will remove the keyboard
            logger_instance=logger,
            log_context=f"process_user_action_selection ({callback_data.action.value}) on {server_host_for_display}",
        )
        # The original code had a two-step fallback to remove markup if edit_text failed.
        # safe_edit_text attempts to edit text and markup together. If it fails, it logs.
        # For simplicity and DRY, we rely on this single call. If removing markup
        # specifically after a text edit failure is critical and common, safe_edit_text
        # would need to be enhanced or a more complex structure kept.
        # Given typical usage, this simplification is usually acceptable.
    else:
        await callback_query.answer(message_text, show_alert=True)
