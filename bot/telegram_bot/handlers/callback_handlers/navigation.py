import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

from bot.telegram_bot.keyboards import create_main_settings_keyboard
from bot.telegram_bot.callback_data import SettingsCallback # For "back_to_main"

logger = logging.getLogger(__name__)
navigation_router = Router(name="callback_handlers.navigation")

@navigation_router.callback_query(SettingsCallback.filter(F.action == "back_to_main"))
async def cq_back_to_main_settings_menu(
    callback_query: CallbackQuery,
    _: callable, # Translator
    callback_data: SettingsCallback # Consumed by filter
):
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with callback.")) # GENERIC_NO_MESSAGE_CALLBACK_ERROR
        return
    await callback_query.answer() # Acknowledge the button press

    main_settings_builder = create_main_settings_keyboard(_)
    main_settings_text = _("⚙️ Settings") # SETTINGS_MENU_HEADER (Localized)

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

# Add other general navigation handlers here if any, e.g.:
# @navigation_router.callback_query(F.data == "close_menu")
# async def process_close_menu(callback_query: CallbackQuery, _: callable):
#     await callback_query.answer(_("MENU_CLOSED_TOAST"))
#     try:
#         await callback_query.message.delete()
#     except TelegramAPIError as e:
#         logger.error(f"Error deleting message on close_menu: {e}")

# @navigation_router.callback_query(F.data == "dummy_action")
# async def process_dummy_tap(callback_query: CallbackQuery, _: callable):
#     await callback_query.answer(_("DUMMY_BUTTON_TOAST"))
