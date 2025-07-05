import logging
from typing import Callable # Added import for Callable
from aiogram import Router, F, Bot as AiogramBot # Renamed Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, BotCommandScopeChat
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from aiogram.exceptions import TelegramAPIError

from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_main_settings_keyboard, create_language_selection_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, LanguageCallback
from bot.core.enums import SettingsNavAction, LanguageAction
# from bot.core.languages import AVAILABLE_LANGUAGES_DATA # No longer needed
from ._helpers import safe_edit_text
from bot.telegram_bot.commands import get_user_commands, get_admin_commands
from bot.core.user_settings import update_user_settings_in_db

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)
language_router = Router(name="callback_handlers.language")

@language_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.LANGUAGE))
async def cq_show_language_menu(
    callback_query: CallbackQuery,
    _: callable,
    callback_data: SettingsCallback,
    app: "Application"
):
    await callback_query.answer()

    language_menu_builder = await create_language_selection_keyboard(_, available_languages=app.available_languages)

    # Ensure callback_query.message exists before trying to edit
    if not callback_query.message:
        logger.warning("cq_show_language_menu: callback_query.message is None, cannot edit.")
        return

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
    _: Callable[[str], str],
    callback_data: LanguageCallback,
    app: "Application"
):
    if callback_data.lang_code is None:
        logger.warning("LanguageCallback received with lang_code=None")
        await callback_query.answer(_("Invalid language selection."), show_alert=True)
        return

    # Ensure callback_query.message and callback_query.from_user exist
    if not callback_query.message or not callback_query.from_user:
        logger.warning("cq_set_language: callback_query.message or from_user is None.")
        await callback_query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    managed_user_settings = await session.merge(user_settings)
    new_lang_code_str = callback_data.lang_code
    original_lang_code_str = managed_user_settings.language_code

    if new_lang_code_str == original_lang_code_str:
        await callback_query.answer()
        return

    selected_lang_info = next((lang for lang in app.available_languages if lang["code"] == new_lang_code_str), None)
    if not selected_lang_info:
        logger.error(f"Attempt to set unknown language code: {new_lang_code_str}")
        await callback_query.answer(_("Selected language is not available."), show_alert=True)
        return

    new_lang_translator_obj = app.get_translator(new_lang_code_str)
    new_gettext_func = new_lang_translator_obj.gettext

    managed_user_settings.language_code = new_lang_code_str
    is_admin = managed_user_settings.telegram_id in app.admin_ids_cache

    try:
        # 1. Сохраняем в БД
        await update_user_settings_in_db(session, managed_user_settings)

        # 2. <<< ВАЖНО: НЕМЕДЛЕННО ОБНОВЛЯЕМ КЭШ >>>
        app.user_settings_cache[managed_user_settings.telegram_id] = managed_user_settings

        # 3. Теперь отвечаем пользователю и обновляем UI
        await callback_query.answer(
            new_gettext_func("Language updated to {lang_name}.").format(lang_name=selected_lang_info["native_name"]),
            show_alert=False
        )

        scope = BotCommandScopeChat(chat_id=callback_query.from_user.id)
        commands_to_set = get_admin_commands(new_gettext_func) if is_admin else get_user_commands(new_gettext_func)

        active_bot_instance = app.tg_bot_event
        await active_bot_instance.delete_my_commands(scope=scope)
        await active_bot_instance.set_my_commands(commands=commands_to_set, scope=scope)
        logger.info(f"Updated Telegram commands for user {callback_query.from_user.id} to language '{new_lang_code_str}'.")

        main_settings_builder = await create_main_settings_keyboard(new_gettext_func)
        main_settings_text = new_gettext_func("Settings")

        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=main_settings_text,
            reply_markup=main_settings_builder.as_markup(),
            logger_instance=logger,
            log_context="cq_set_language_ui_refresh"
        )
    except SQLAlchemyError as e_db:
        logger.error(f"Failed to update language settings in DB for user {callback_query.from_user.id}. Error: {e_db}", exc_info=True)
        managed_user_settings.language_code = original_lang_code_str
        await callback_query.answer(_("An error occurred during language update. Please try again."), show_alert=True)
    except TelegramAPIError as e_tg:
        logger.error(f"Telegram API error setting commands for user {callback_query.from_user.id} after language change: {e_tg}", exc_info=True)
        await callback_query.answer(
            new_gettext_func("Language updated, but commands might not refresh immediately. Error: {error_msg}").format(error_msg=str(e_tg)),
            show_alert=True
        )
        main_settings_builder = await create_main_settings_keyboard(new_gettext_func)
        main_settings_text = new_gettext_func("Settings")
        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=main_settings_text,
            reply_markup=main_settings_builder.as_markup(),
            logger_instance=logger,
            log_context="cq_set_language_ui_refresh_after_tg_error"
        )
    except Exception as e:
        logger.error(f"An unexpected error occurred while changing language for user {callback_query.from_user.id}: {e}", exc_info=True)
        if not isinstance(e, (SQLAlchemyError, TelegramAPIError)):
             managed_user_settings.language_code = original_lang_code_str
        await callback_query.answer(_("An unexpected error occurred."), show_alert=True)
