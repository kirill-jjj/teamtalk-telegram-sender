# bot/telegram_bot/handlers/callback_handlers/_helpers.py
import logging
from typing import Callable
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from bot.models import UserSettings
from bot.core.user_settings import update_user_settings_in_db

logger = logging.getLogger(__name__)

async def process_setting_update(
    callback_query: CallbackQuery,
    session: AsyncSession,
    user_settings: UserSettings,
    _: callable,
    update_action: Callable[[], None],
    revert_action: Callable[[], None],
    success_toast_text: str,
    ui_refresh_callable: Callable[[], tuple[str, InlineKeyboardMarkup]]
) -> None:
    # Ensure message and from_user are present, crucial for callback context
    if not callback_query.message or not callback_query.from_user:
        logger.warning("process_setting_update: Callback query is missing message or from_user.")
        # Try to answer callback even if message context is faulty, to acknowledge interaction
        try:
            await callback_query.answer(_("Error: Callback query is missing essential data."), show_alert=True)
        except TelegramAPIError as ans_err_crit: # Catch if even answering fails
            logger.error(f"Critical error: Failed to answer callback for missing data: {ans_err_crit}")
        return

    update_action() # Apply change in-memory first

    try:
        # ИЗМЕНЕНИЕ: Убираем лишний аргумент telegram_id.
        # Теперь функция принимает только сессию и объект настроек.
        await update_user_settings_in_db(session, user_settings)
        # Send toast only on successful DB update
        await callback_query.answer(success_toast_text, show_alert=False)

        # Attempt to refresh UI only after successful DB update and toast
        try:
            new_text, new_markup = ui_refresh_callable()
            await callback_query.message.edit_text(text=new_text, reply_markup=new_markup)
        except TelegramBadRequest as e_br:
            if "message is not modified" not in str(e_br).lower(): # Common, safe to ignore
                logger.error(f"TelegramBadRequest refreshing UI after setting update: {e_br}", exc_info=True)
        except TelegramAPIError as e_api: # More general API errors
            logger.error(f"TelegramAPIError refreshing UI after setting update: {e_api}", exc_info=True)
        except Exception as e_ui: # Catch any other exception during UI refresh
            logger.error(f"Generic error refreshing UI after setting update: {e_ui}", exc_info=True)

    except Exception as e_db: # Catch errors from update_user_settings_in_db or initial callback_query.answer
        logger.error(f"Failed to update settings in DB for user {callback_query.from_user.id}. Error: {e_db}", exc_info=True)
        revert_action() # Revert in-memory change
        try:
            await callback_query.answer(_("An error occurred."), show_alert=True)
        except TelegramAPIError as ans_err_revert:
            logger.warning(f"Could not send error alert for DB update failure/revert: {ans_err_revert}")
        # Do not proceed to UI refresh if DB update failed
        return
