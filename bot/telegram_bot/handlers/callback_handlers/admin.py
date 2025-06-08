import logging
from aiogram import Router, F, html
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.exceptions import PermissionError as PytalkPermissionError

from bot.telegram_bot.filters import IsAdminFilter
from bot.telegram_bot.callback_data import AdminActionCallback
from bot.core.utils import get_tt_user_display_name

logger = logging.getLogger(__name__)
admin_actions_router = Router(name="callback_handlers.admin")
ttstr = pytalk.instance.sdk.ttstr

async def _execute_tt_user_action(
    action_val: str,
    user_id_val: int,
    user_nickname_val: str,
    _: callable,
    tt_instance: TeamTalkInstance,
    admin_tg_id: int
) -> str:
    try:
        user_to_act_on = tt_instance.get_user(user_id_val)
        if not user_to_act_on:
            return _("User not found on server anymore.")

        quoted_nickname = html.quote(user_nickname_val)
        if action_val == "kick":
            user_to_act_on.kick(from_server=True)
            logger.info(f"Admin {admin_tg_id} kicked TT user '{user_nickname_val}' (ID: {user_id_val})")
            return _("User {user_nickname} kicked from server.").format(user_nickname=quoted_nickname)
        elif action_val == "ban":
            user_to_act_on.ban(from_server=True)
            user_to_act_on.kick(from_server=True)
            logger.info(f"Admin {admin_tg_id} banned and kicked TT user '{user_nickname_val}' (ID: {user_id_val})")
            return _("User {user_nickname} banned and kicked from server.").format(user_nickname=quoted_nickname)
        else:
            return _("Unknown action.")
    except PytalkPermissionError as e:
        logger.error(f"PermissionError during '{action_val}' on TT user ID {user_id_val}: {e}")
        return _("You do not have permission to perform this action on the server.")
    except Exception as e:
        logger.error(f"Error during '{action_val}' on TT user ID {user_id_val}: {e}", exc_info=True)
        return _("An error occurred during the action on the user.")

@admin_actions_router.callback_query(AdminActionCallback.filter(F.action.in_({"kick", "ban"})))
async def process_user_action_selection(
    callback_query: CallbackQuery,
    callback_data: AdminActionCallback,
    session: AsyncSession,
    _: callable,
    tt_instance: TeamTalkInstance | None
):
    await callback_query.answer()
    if not callback_query.message or not callback_query.from_user: return
    if not tt_instance or not tt_instance.connected:
         await callback_query.message.edit_text(_("TeamTalk bot is not connected."))
         return

    is_admin_caller = await IsAdminFilter()(callback_query, session)
    if not is_admin_caller:
        await callback_query.answer(_("You do not have permission to execute this action."), show_alert=True)
        return

    user_to_act_on = tt_instance.get_user(callback_data.user_id)
    if not user_to_act_on:
        await callback_query.message.edit_text(_("User not found on server anymore."))
        return

    user_nickname_val = get_tt_user_display_name(user_to_act_on, _)

    reply_text_val = await _execute_tt_user_action(
        action_val=callback_data.action,
        user_id_val=callback_data.user_id,
        user_nickname_val=user_nickname_val,
        _=_,
        tt_instance=tt_instance,
        admin_tg_id=callback_query.from_user.id
    )

    try:
        await callback_query.message.edit_text(reply_text_val, reply_markup=None)
    except TelegramAPIError as e:
        logger.error(f"Error editing message after user action callback: {e}")
