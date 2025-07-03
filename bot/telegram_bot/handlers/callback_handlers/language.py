import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_main_settings_keyboard, create_language_selection_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, LanguageCallback
from bot.core.enums import SettingsNavAction, LanguageAction
from bot.language import get_translator
from bot.core.languages import AVAILABLE_LANGUAGES_DATA, DEFAULT_LANGUAGE_CODE
from ._helpers import process_setting_update, safe_edit_text

logger = logging.getLogger(__name__)
language_router = Router(name="callback_handlers.language")

@language_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.LANGUAGE))
async def cq_show_language_menu(
    callback_query: CallbackQuery,
    _: callable,
    callback_data: SettingsCallback
):
    await callback_query.answer()

    language_menu_builder = create_language_selection_keyboard(_)

    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=_("Please choose your language:"),
        reply_markup=language_menu_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_language_menu"
    )

@language_router.callback_query(LanguageCallback.filter(F.action == LanguageAction.SET_LANG))
async def cq_set_language(
    callback_query: CallbackQuery,
    session: AsyncSession,
    user_settings: UserSettings,
    _: callable,
    callback_data: LanguageCallback
):
    if callback_data.lang_code is None:
        # Should not happen if buttons always provide lang_code
        logger.warning("LanguageCallback received with lang_code=None")
        await callback_query.answer("Invalid language selection.", show_alert=True)
        return

    managed_user_settings = await session.merge(user_settings)
    new_lang_code_str = callback_data.lang_code # This is now a string e.g. "en", "ru"
    original_lang_code_str = managed_user_settings.language_code

    if new_lang_code_str == original_lang_code_str:
        await callback_query.answer() # No change
        return

    # Validate if the new_lang_code_str is actually one of the discovered languages
    selected_lang_info = next((lang for lang in AVAILABLE_LANGUAGES_DATA if lang["code"] == new_lang_code_str), None)
    if not selected_lang_info:
        logger.error(f"Attempt to set unknown language code: {new_lang_code_str}")
        await callback_query.answer("Selected language is not available.", show_alert=True)
        return

    new_lang_translator_obj = get_translator(new_lang_code_str)

    def update_logic():
        managed_user_settings.language_code = new_lang_code_str

    def revert_logic():
        managed_user_settings.language_code = original_lang_code_str

    # Use the native_name from selected_lang_info for the toast message
    lang_name_display = selected_lang_info["native_name"]
    success_toast_text = new_lang_translator_obj.gettext("Language updated to {lang_name}.").format(lang_name=lang_name_display)

    # After language change, the main settings menu should be rendered using the new language
    main_settings_builder = create_main_settings_keyboard(new_lang_translator_obj.gettext)
    main_settings_text = new_lang_translator_obj.gettext("Settings")

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=managed_user_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        new_text=main_settings_text,
        new_markup=main_settings_builder.as_markup()
    )
