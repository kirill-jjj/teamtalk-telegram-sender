import logging
from aiogram import Router, F, html
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramAPIError
import pytalk
# from pytalk.instance import TeamTalkInstance # Will use tt_connection.instance
from pytalk.exceptions import PermissionError as PytalkPermissionError, TeamTalkException as PytalkException
from bot.teamtalk_bot.connection import TeamTalkConnection # For type hinting

from bot.telegram_bot.callback_data import AdminActionCallback
from bot.core.enums import AdminAction
from bot.core.utils import get_tt_user_display_name

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)
admin_actions_router = Router(name="callback_handlers.admin")
# TeamTalkConnectionCheckMiddleware is assumed to be applied globally or on a parent router.

ttstr = pytalk.instance.sdk.ttstr # Keep if get_tt_user_display_name or other utils use it.

async def _execute_tt_user_action(
    action: AdminAction,
    user_to_act_on: pytalk.user.User, # This user object is tied to a specific tt_instance
    _: callable,
    admin_tg_id: int,
    server_host: str # For logging context
) -> tuple[bool, str]:
    """
    Executes a moderation action on a TeamTalk user.
    Returns a tuple of (success_boolean, message_string).
    """
    user_nickname = get_tt_user_display_name(user_to_act_on, _)
    quoted_nickname = html.quote(user_nickname)

    try:
        if action == AdminAction.KICK:
            user_to_act_on.kick(from_server=True) # kick method on User object uses its associated instance
            logger.info(f"Admin {admin_tg_id} kicked TT user '{user_nickname}' (ID: {user_to_act_on.id}) from server {server_host}")
            return True, _("User {user_nickname} kicked from server {server_host}.").format(user_nickname=quoted_nickname, server_host=server_host)
        elif action == AdminAction.BAN:
            user_to_act_on.ban(from_server=True) # ban method on User object
            user_to_act_on.kick(from_server=True) # kick as well after ban
            logger.info(f"Admin {admin_tg_id} banned and kicked TT user '{user_nickname}' (ID: {user_to_act_on.id}) from server {server_host}")
            return True, _("User {user_nickname} banned and kicked from server {server_host}.").format(user_nickname=quoted_nickname, server_host=server_host)
        else:
            logger.warning(f"Unknown action '{action}' passed to _execute_tt_user_action for server {server_host}.")
            return False, _("Unknown action.")

    except PytalkPermissionError as e:
        logger.error(f"PermissionError during '{action}' on TT user ID {user_to_act_on.id} on server {server_host}: {e}")
        return False, _("The bot lacks permissions on the TeamTalk server {server_host} to perform this action.").format(server_host=server_host)
    except PytalkException as e:
        logger.error(f"TeamTalkException during '{action}' on TT user ID {user_to_act_on.id} on server {server_host}: {e}", exc_info=True)
        return False, _("An error occurred on server {server_host} during the action on the user: {error}").format(server_host=server_host, error=str(e))
    except (ValueError, TypeError, AttributeError) as e_data: # Includes issues if user_to_act_on is somehow invalid
        logger.error(f"Data error during '{action}' on TT user (ID: {user_to_act_on.id if hasattr(user_to_act_on, 'id') else 'UNKNOWN'}) on server {server_host}: {e_data}", exc_info=True)
        return False, _("An internal data error occurred processing the request for server {server_host}.").format(server_host=server_host)
    except (TimeoutError, OSError) as e_net: # Network or OS level errors
        logger.critical(f"CRITICAL: Network/OS error during '{action}' on TT user (ID: {user_to_act_on.id if hasattr(user_to_act_on, 'id') else 'UNKNOWN'}) on server {server_host}: {e_net}", exc_info=True)
        return False, _("A network or system error occurred with server {server_host}. Administrator has been notified.").format(server_host=server_host)


@admin_actions_router.callback_query(
    AdminActionCallback.filter(F.action.in_({AdminAction.KICK, AdminAction.BAN}))
    # Removed F.from_user.id.in_(ADMIN_IDS_CACHE) - will check manually
)
async def process_user_action_selection(
    callback_query: CallbackQuery,
    callback_data: AdminActionCallback,
    _: callable,
    app: "Application", # Injected by ApplicationMiddleware
    tt_connection: TeamTalkConnection | None # Injected by ActiveTeamTalkConnectionMiddleware & checked by TeamTalkConnectionCheckMiddleware
):
    if not callback_query.message: # Should be handled by ensure_message_context if that's used, or check here
        await callback_query.answer(_("Error: Message context not found."), show_alert=True)
        return

    if callback_query.from_user.id not in app.admin_ids_cache:
        await callback_query.answer(_("You are not authorized for this action."), show_alert=True)
        return

    # TeamTalkConnectionCheckMiddleware should ensure tt_connection and tt_connection.instance are valid
    if not tt_connection or not tt_connection.instance:
         # This case should ideally be caught by TeamTalkConnectionCheckMiddleware if applied to this router
         await callback_query.answer(_("TeamTalk bot is not connected or connection is not ready."), show_alert=True)
         return

    tt_instance = tt_connection.instance
    server_host_for_display = tt_connection.server_info.host

    user_to_act_on = tt_instance.get_user(callback_data.user_id) # Get user from specific instance
    if not user_to_act_on:
        await callback_query.answer(_("User not found on server {server_host} anymore.").format(server_host=server_host_for_display), show_alert=True)
        try:
            # Try to remove buttons if user is gone
            if callback_query.message: # Check if message exists
                 await callback_query.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            logger.debug(f"Failed to remove reply markup when user {callback_data.user_id} was not found on {server_host_for_display}.")
        return

    success, message_text = await _execute_tt_user_action(
        action=callback_data.action,
        user_to_act_on=user_to_act_on,
        _=_,
        admin_tg_id=callback_query.from_user.id,
        server_host=server_host_for_display # Pass server_host for context
    )

    if success:
        await callback_query.answer(_("Success!"), show_alert=False)
        # Edit the original message (e.g., the one with user selection buttons)
        if callback_query.message: # Check if message exists
            try:
                await callback_query.message.edit_text(message_text, reply_markup=None)
            except TelegramAPIError as e:
                # If editing text fails (e.g. message too old, or not text based), try just removing markup
                logger.warning(f"Failed to edit message text after user action on {server_host_for_display}: {e}. Trying to edit reply markup only.")
                try:
                    await callback_query.message.edit_reply_markup(reply_markup=None)
                except TelegramAPIError as e_markup:
                    logger.error(f"Failed to even remove reply markup after user action on {server_host_for_display}: {e_markup}")
    else:
        # For failures, message_text from _execute_tt_user_action already includes server_host context
        await callback_query.answer(message_text, show_alert=True)
