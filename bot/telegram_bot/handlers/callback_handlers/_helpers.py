import logging
from typing import Callable
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from bot.core.user_settings import UserSpecificSettings, update_user_settings_in_db

logger = logging.getLogger(__name__)

async def process_setting_update(
    callback_query: CallbackQuery,
    session: AsyncSession,
    user_settings: UserSpecificSettings,
    _: callable,
    update_action: Callable[[], None],
    revert_action: Callable[[], None],
    success_toast_text: str,
    ui_refresh_callable: Callable[[], tuple[str, InlineKeyboardMarkup]]
) -> None:
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer("Error: Callback query is missing essential data.", show_alert=True)
        return

    update_action()

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_settings)
        await callback_query.answer(success_toast_text, show_alert=False)
    except Exception as e:
        logger.error(f"Failed to update settings in DB for user {callback_query.from_user.id}. Error: {e}", exc_info=True)
        revert_action()
        try:
            await callback_query.answer(_("An error occurred."), show_alert=True)
        except TelegramAPIError as ans_err:
            logger.warning(f"Could not send error alert for DB update failure: {ans_err}")
        return

    try:
        new_text, new_markup = ui_refresh_callable()
        await callback_query.message.edit_text(text=new_text, reply_markup=new_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message after setting update: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message after setting update: {e}")
