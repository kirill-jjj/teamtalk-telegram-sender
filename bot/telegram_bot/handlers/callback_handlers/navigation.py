import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

from bot.telegram_bot.keyboards import create_main_settings_keyboard
from bot.telegram_bot.callback_data import SettingsCallback
from bot.core.enums import SettingsNavAction
from ._helpers import safe_edit_text # Import the new helper

logger = logging.getLogger(__name__)
navigation_router = Router(name="callback_handlers.navigation")

@navigation_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.BACK_TO_MAIN))
async def cq_back_to_main_settings_menu(
    callback_query: CallbackQuery,
    _: callable,
    callback_data: SettingsCallback
):
    await callback_query.answer()

    main_settings_builder = create_main_settings_keyboard(_)
    main_settings_text = _("Settings")

    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=main_settings_text,
        reply_markup=main_settings_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_back_to_main_settings_menu"
    )
