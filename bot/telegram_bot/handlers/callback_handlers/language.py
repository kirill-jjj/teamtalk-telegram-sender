import logging
from typing import Callable # Added import for Callable
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, BotCommandScopeChat
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from aiogram.exceptions import TelegramAPIError

from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_main_settings_keyboard, create_language_selection_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, LanguageCallback
from bot.core.enums import SettingsNavAction, LanguageAction
from bot.language import get_translator
from bot.core.languages import AVAILABLE_LANGUAGES_DATA # DEFAULT_LANGUAGE_CODE is not used here directly
from ._helpers import safe_edit_text # process_setting_update is replaced by direct logic
from bot.telegram_bot.commands import get_user_commands, get_admin_commands # For setting commands
from bot.state import ADMIN_IDS_CACHE # To check if user is admin
from bot.core.user_settings import update_user_settings_in_db # Corrected path to function

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
    _: Callable[[str], str], # Now it's gettext for current user language
    callback_data: LanguageCallback,
    bot: Bot # Added bot argument
):
    if callback_data.lang_code is None:
        logger.warning("LanguageCallback received with lang_code=None")
        await callback_query.answer(_("Invalid language selection."), show_alert=True)
        return

    managed_user_settings = await session.merge(user_settings)
    new_lang_code_str = callback_data.lang_code
    original_lang_code_str = managed_user_settings.language_code

    if new_lang_code_str == original_lang_code_str:
        await callback_query.answer() # Language didn't change, do nothing
        return

    selected_lang_info = next((lang for lang in AVAILABLE_LANGUAGES_DATA if lang["code"] == new_lang_code_str), None)
    if not selected_lang_info:
        logger.error(f"Attempt to set unknown language code: {new_lang_code_str}")
        await callback_query.answer(_("Selected language is not available."), show_alert=True)
        return

    # Get new translator object for the selected language
    new_lang_translator_obj = get_translator(new_lang_code_str)
    new_gettext_func = new_lang_translator_obj.gettext

    # Logic to update user settings (in-memory first)
    managed_user_settings.language_code = new_lang_code_str

    # Check if the user is an admin
    is_admin = managed_user_settings.telegram_id in ADMIN_IDS_CACHE

    try:
        # First, update user settings in the database
        await update_user_settings_in_db(session, managed_user_settings) # Assuming this function commits

        # Send a toast notification about successful update
        await callback_query.answer(
            new_gettext_func("Language updated to {lang_name}.").format(lang_name=selected_lang_info["native_name"]),
            show_alert=False
        )

        # After successful settings update, set commands for this specific user
        scope = BotCommandScopeChat(chat_id=callback_query.from_user.id)
        # Determine which commands to set (user or admin)
        commands_to_set = get_admin_commands(new_gettext_func) if is_admin else get_user_commands(new_gettext_func)

        # Delete previous custom commands for this chat
        await bot.delete_my_commands(scope=scope)
        # Set new localized commands
        await bot.set_my_commands(commands=commands_to_set, scope=scope)
        logger.info(f"Updated Telegram commands for user {callback_query.from_user.id} to language '{new_lang_code_str}'.")

        # Now update the Telegram message interface (keyboard and text)
        main_settings_builder = create_main_settings_keyboard(new_gettext_func)
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
        # Revert in-memory change
        managed_user_settings.language_code = original_lang_code_str
        await callback_query.answer(_("An error occurred during language update. Please try again."), show_alert=True)
    except TelegramAPIError as e_tg:
        logger.error(f"Telegram API error setting commands for user {callback_query.from_user.id} after language change: {e_tg}", exc_info=True)
        # If commands failed to update on Telegram's side, but language in DB is saved,
        # still update the UI to reflect the language change. The user message reflects this.
        await callback_query.answer(
            _("Language updated, but commands might not refresh immediately. Error: {error_msg}").format(error_msg=str(e_tg)),
            show_alert=True
        )
        # Even if commands fail to set, ensure UI is updated to new language
        main_settings_builder = create_main_settings_keyboard(new_gettext_func)
        main_settings_text = new_gettext_func("Settings")
        if callback_query.message: # Ensure message exists
            await safe_edit_text(
                message_to_edit=callback_query.message,
                text=main_settings_text,
                reply_markup=main_settings_builder.as_markup(),
                logger_instance=logger,
                log_context="cq_set_language_ui_refresh_after_tg_error"
            )
    except Exception as e:
        logger.error(f"An unexpected error occurred while changing language for user {callback_query.from_user.id}: {e}", exc_info=True)
        # Revert in-memory change if not a DB/TG error that already handled it or has specific user message
        if not isinstance(e, (SQLAlchemyError, TelegramAPIError)):
             managed_user_settings.language_code = original_lang_code_str
        await callback_query.answer(_("An unexpected error occurred."), show_alert=True)
