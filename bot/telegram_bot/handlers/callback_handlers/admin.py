import logging
from aiogram import Router, F, html
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramAPIError
import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.exceptions import PermissionError as PytalkPermissionError, TeamTalkException as PytalkException

from bot.state import ADMIN_IDS_CACHE
from bot.telegram_bot.callback_data import AdminActionCallback
from bot.core.enums import AdminAction
from bot.core.utils import get_tt_user_display_name

logger = logging.getLogger(__name__)
admin_actions_router = Router(name="callback_handlers.admin")
ttstr = pytalk.instance.sdk.ttstr

async def _execute_tt_user_action(
    action: AdminAction,
    user_to_act_on: pytalk.user.User,
    _: callable,
    admin_tg_id: int
) -> tuple[bool, str]:
    """
    Executes a moderation action on a TeamTalk user.
    Returns a tuple of (success_boolean, message_string).
    """
    user_nickname = get_tt_user_display_name(user_to_act_on, _)
    quoted_nickname = html.quote(user_nickname)

    try:
        if action == AdminAction.KICK:
            user_to_act_on.kick(from_server=True)
            logger.info(f"Admin {admin_tg_id} kicked TT user '{user_nickname}' (ID: {user_to_act_on.id})")
            return True, _("User {user_nickname} kicked from server.").format(user_nickname=quoted_nickname)
        elif action == AdminAction.BAN:
            user_to_act_on.ban(from_server=True)
            user_to_act_on.kick(from_server=True)
            logger.info(f"Admin {admin_tg_id} banned and kicked TT user '{user_nickname}' (ID: {user_to_act_on.id})")
            return True, _("User {user_nickname} banned and kicked from server.").format(user_nickname=quoted_nickname)
        else:
            logger.warning(f"Unknown action '{action}' passed to _execute_tt_user_action.")
            return False, _("Unknown action.")

    except PytalkPermissionError as e:
        logger.error(f"PermissionError during '{action}' on TT user ID {user_to_act_on.id}: {e}")
        return False, _("The bot lacks permissions on the TeamTalk server to perform this action.")
    except PytalkException as e:
        logger.error(f"TeamTalkException during '{action}' on TT user ID {user_to_act_on.id}: {e}", exc_info=True)
        return False, _("An error occurred during the action on the user: {error}").format(error=str(e))
    except (ValueError, TypeError, AttributeError) as e_data:
        logger.error(f"Data error during '{action}' on TT user ID {user_to_act_on.id if hasattr(user_to_act_on, 'id') else 'UNKNOWN'}: {e_data}", exc_info=True)
        return False, _("An internal data error occurred processing the request.") # Already wrapped, confirming
    except (TimeoutError, OSError) as e:
        logger.critical(f"CRITICAL: Network/OS error during '{action}' on TT user ID {user_to_act_on.id if hasattr(user_to_act_on, 'id') else 'UNKNOWN'}: {e}", exc_info=True)
        return False, _("A network or system error occurred. Administrator has been notified.") # Already wrapped, confirming


@admin_actions_router.callback_query(
    AdminActionCallback.filter(F.action.in_({AdminAction.KICK, AdminAction.BAN})),
    F.from_user.id.in_(ADMIN_IDS_CACHE)
)
async def process_user_action_selection(
    callback_query: CallbackQuery,
    callback_data: AdminActionCallback,
    _: callable,
    tt_instance: TeamTalkInstance | None
):
    if not tt_instance or not tt_instance.connected:
         await callback_query.answer(_("TeamTalk bot is not connected."), show_alert=True)
         return

    user_to_act_on = tt_instance.get_user(callback_data.user_id)
    if not user_to_act_on:
        await callback_query.answer(_("User not found on server anymore."), show_alert=True)
        try:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            logger.debug(f"Failed to remove reply markup when user {callback_data.user_id} was not found.")
            pass
        return

    success, message_text = await _execute_tt_user_action(
        action=callback_data.action,
        user_to_act_on=user_to_act_on,
        _=_,
        admin_tg_id=callback_query.from_user.id
    )

    if success:
        await callback_query.answer(_("Success!"), show_alert=False)
        try:
            await callback_query.message.edit_text(message_text, reply_markup=None)
        except TelegramAPIError as e:
            logger.error(f"Error editing message after successful user action: {e}")
    else:
        await callback_query.answer(message_text, show_alert=True)
