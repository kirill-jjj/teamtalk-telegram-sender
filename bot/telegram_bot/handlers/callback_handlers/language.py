import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.user_settings import UserSpecificSettings
from bot.telegram_bot.keyboards import create_main_settings_keyboard, create_language_selection_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, LanguageCallback
from bot.core.enums import SettingsNavAction, LanguageAction
from bot.language import get_translator
from ._helpers import process_setting_update # Import from local _helpers

logger = logging.getLogger(__name__)
language_router = Router(name="callback_handlers.language")

@language_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.LANGUAGE))
async def cq_show_language_menu(
    callback_query: CallbackQuery,
    _: callable,
    callback_data: SettingsCallback # Consumed but not directly used, could be removed if not needed by filter
):
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with callback."))
        return
    await callback_query.answer()

    language_menu_builder = create_language_selection_keyboard(_)

    try:
        await callback_query.message.edit_text(
            text=_("Please choose your language:"), # CHOOSE_LANGUAGE_PROMPT
            reply_markup=language_menu_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for language selection: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for language selection: {e}")

@language_router.callback_query(LanguageCallback.filter(F.action == LanguageAction.SET_LANG))
async def cq_set_language(
    callback_query: CallbackQuery,
    session: AsyncSession,
    user_specific_settings: UserSpecificSettings,
    _: callable, # Translator for current language, used by process_setting_update for potential error messages
    callback_data: LanguageCallback
):
    if not callback_query.message or not callback_query.from_user or not callback_data.lang_code:
        await callback_query.answer(_("Error: Missing data for language update."), show_alert=True)
        return

    new_lang_code = callback_data.lang_code
    original_lang_code = user_specific_settings.language

    if new_lang_code == original_lang_code:
        await callback_query.answer() # Already this language, do nothing
        return

    new_lang_translator_obj = get_translator(new_lang_code)
    _new = new_lang_translator_obj.gettext

    def update_logic():
        user_specific_settings.language = new_lang_code

    def revert_logic():
        user_specific_settings.language = original_lang_code

    # Assuming keys like "LANGUAGE_BTN_EN" exist and give "English" when _new is for "en"
    lang_name_display = _new(f"LANGUAGE_BTN_{new_lang_code.upper()}")
    success_toast_text = _new("Language updated to {lang_name}.").format(lang_name=lang_name_display) # LANGUAGE_UPDATED_TO

    def refresh_ui_callable() -> tuple[str, InlineKeyboardMarkup]:
        # UI should be in the new language
        main_settings_builder = create_main_settings_keyboard(_new)
        main_settings_text = _new("⚙️ Settings") # SETTINGS_MENU_HEADER
        return main_settings_text, main_settings_builder.as_markup()

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        _=_, # Pass original language translator for generic error messages from process_setting_update
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text, # This will be in the new language
        ui_refresh_callable=refresh_ui_callable # This will generate UI in the new language
    )
