import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_main_settings_keyboard, create_language_selection_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, LanguageCallback
from bot.core.enums import SettingsNavAction, LanguageAction
from bot.language import get_translator
from bot.core.languages import Language # <--- ДОБАВЛЕНО
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
    # callback_data.lang_code — это строка, поэтому преобразуем её в Enum
    new_lang_code_enum = Language(callback_data.lang_code) # <--- ИЗМЕНЕНО
    original_lang_code_enum = managed_user_settings.language # Теперь это Enum

    if new_lang_code_enum == original_lang_code_enum:
        await callback_query.answer()
        return

    new_lang_translator_obj = get_translator(new_lang_code_enum.value) # <--- ИЗМЕНЕНО

    def update_logic():
        managed_user_settings.language = new_lang_code_enum # <--- ИЗМЕНЕНО

    def revert_logic():
        managed_user_settings.language = original_lang_code_enum # <--- ИЗМЕНЕНО

    lang_display_map = {
        Language.ENGLISH: new_lang_translator_obj.gettext("English"), # <--- ИЗМЕНЕНО
        Language.RUSSIAN: new_lang_translator_obj.gettext("Russian"), # <--- ИЗМЕНЕНО
    }
    lang_name_display = lang_display_map.get(new_lang_code_enum, new_lang_code_enum.value) # <--- ИЗМЕНЕНО
    success_toast_text = new_lang_translator_obj.gettext("Language updated to {lang_name}.").format(lang_name=lang_name_display)

    # Подготавливаем текст и разметку здесь
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
        new_text=main_settings_text, # <--- ИЗМЕНЕНО
        new_markup=main_settings_builder.as_markup() # <--- ИЗМЕНЕНО
        # ui_refresh_callable=refresh_ui_callable # <--- УДАЛИТЬ
    )
