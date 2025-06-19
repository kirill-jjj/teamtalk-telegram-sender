import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

from bot.telegram_bot.keyboards import create_main_settings_keyboard
from bot.telegram_bot.callback_data import SettingsCallback # For "back_to_main"
from bot.core.enums import SettingsNavAction

logger = logging.getLogger(__name__)
navigation_router = Router(name="callback_handlers.navigation")

@navigation_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.BACK_TO_MAIN))
async def cq_back_to_main_settings_menu(
    callback_query: CallbackQuery,
    _: callable,
    callback_data: SettingsCallback
):
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with this callback."))
        return
    await callback_query.answer()

    main_settings_builder = create_main_settings_keyboard(_)
    main_settings_text = _("Settings")

    try:
        await callback_query.message.edit_text(
            text=main_settings_text,
            reply_markup=main_settings_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            # Log if it's not the "message is not modified" error, which is benign
            logger.error(f"TelegramBadRequest editing message for back_to_main_settings_menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for back_to_main_settings_menu: {e}")
