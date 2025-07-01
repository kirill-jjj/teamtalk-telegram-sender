import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_main_settings_keyboard, create_language_selection_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, LanguageCallback
from bot.core.enums import SettingsNavAction, LanguageAction
from bot.language import get_translator
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
    managed_user_settings = await session.merge(user_settings)
    new_lang_code = callback_data.lang_code
    original_lang_code = managed_user_settings.language

    if new_lang_code == original_lang_code:
        await callback_query.answer()
        return

    new_lang_translator_obj = get_translator(new_lang_code)

    def update_logic():
        managed_user_settings.language = new_lang_code

    def revert_logic():
        managed_user_settings.language = original_lang_code

    lang_display_map = {
        "en": new_lang_translator_obj.gettext("English"),
        "ru": new_lang_translator_obj.gettext("Russian"),
    }
    lang_name_display = lang_display_map.get(new_lang_code, new_lang_code)
    success_toast_text = new_lang_translator_obj.gettext("Language updated to {lang_name}.").format(lang_name=lang_name_display)

    def refresh_ui_callable() -> tuple[str, InlineKeyboardMarkup]:
        main_settings_builder = create_main_settings_keyboard(new_lang_translator_obj.gettext)
        main_settings_text = new_lang_translator_obj.gettext("Settings")
        return main_settings_text, main_settings_builder.as_markup()

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=managed_user_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        ui_refresh_callable=refresh_ui_callable
    )
