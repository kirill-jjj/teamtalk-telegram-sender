"""Callback query handlers for language settings."""

import gettext
import logging

# For type hinting Services
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommandScopeChat, CallbackQuery
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.enums import LanguageAction, SettingsNavAction
from bot.core.user_settings import update_user_settings_in_db
from bot.models import UserSettings
from bot.telegram_bot.callback_data import LanguageCallback, SettingsCallback
from bot.telegram_bot.commands import get_admin_commands, get_user_commands
from bot.telegram_bot.keyboards import create_language_selection_keyboard, create_main_settings_keyboard

from ._helpers import safe_edit_text

if TYPE_CHECKING:
    from bot.services_container import Services  # Import Services

logger = logging.getLogger(__name__)
language_router = Router(name="callback_handlers.language")


@language_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.LANGUAGE))
async def cq_show_language_menu(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    available_languages: list[dict[str, str]],  # Injected from workflow_data
):
    """Shows the language selection menu."""
    _ = translator.gettext
    await callback_query.answer()

    language_menu_builder = await create_language_selection_keyboard(
        translator, available_languages=available_languages
    )

    if not callback_query.message:
        logger.warning("cq_show_language_menu: callback_query.message is None, cannot edit.")
        return

    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=_("Please choose your language:"),
        reply_markup=language_menu_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_language_menu",
    )


@language_router.callback_query(LanguageCallback.filter(F.action == LanguageAction.SET_LANG))
async def cq_set_language(
    callback_query: CallbackQuery,
    session: AsyncSession,  # Injected by DbSessionMiddleware
    user_settings: UserSettings,  # Injected by UserSettingsMiddleware
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware (as part of translator)
    callback_data: LanguageCallback,
    services: "Services",  # Injected from workflow_data
):
    """Sets the user's language preference."""
    _ = translator.gettext
    if callback_data.lang_code is None:
        logger.warning("LanguageCallback received with lang_code=None")
        await callback_query.answer(_("Invalid language selection."), show_alert=True)
        return

    if not callback_query.message or not callback_query.from_user:
        logger.warning("cq_set_language: callback_query.message or from_user is None.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    managed_user_settings = await session.merge(user_settings)
    new_lang_code_str = callback_data.lang_code
    original_lang_code_str = managed_user_settings.language_code

    if new_lang_code_str == original_lang_code_str:
        await callback_query.answer()  # Answer to acknowledge, but do nothing else
        return

    # Use services.available_languages
    selected_lang_info = next(
        (lang for lang in services.available_languages if lang["code"] == new_lang_code_str), None
    )
    if not selected_lang_info:
        logger.error("Attempt to set unknown language code: %s", new_lang_code_str)
        await callback_query.answer(_("Selected language is not available."), show_alert=True)
        return

    # Use services.get_translator
    new_lang_translator_obj = services.get_translator(new_lang_code_str)
    new_gettext_func = new_lang_translator_obj.gettext

    managed_user_settings.language_code = new_lang_code_str
    is_admin = services.cache.is_admin(managed_user_settings.telegram_id) # Use CacheService

    try:
        await update_user_settings_in_db(session, managed_user_settings)
        services.cache.update_user_settings(managed_user_settings) # Use CacheService

        await callback_query.answer(
            new_gettext_func("Language updated to {lang_name}.").format(lang_name=selected_lang_info["native_name"]),
            show_alert=False,
        )

        scope = BotCommandScopeChat(chat_id=callback_query.from_user.id)
        commands_to_set = get_admin_commands(new_gettext_func) if is_admin else get_user_commands(new_gettext_func)

        # Use services.bot_event
        active_bot_instance = services.bot_event
        await active_bot_instance.delete_my_commands(scope=scope)
        await active_bot_instance.set_my_commands(commands=commands_to_set, scope=scope)
        logger.info(
            "Updated Telegram commands for user %s to language '%s'.",
            callback_query.from_user.id,
            new_lang_code_str,
        )

        main_settings_builder = await create_main_settings_keyboard(new_gettext_func)
        main_settings_text = new_gettext_func("Settings")

        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=main_settings_text,
            reply_markup=main_settings_builder.as_markup(),
            logger_instance=logger,
            log_context="cq_set_language_ui_refresh",
        )
    except SQLAlchemyError as e_db:
        logger.exception(
            "Failed to update language settings in DB for user %s. Error: %s",
            callback_query.from_user.id,
            e_db,
        )
        managed_user_settings.language_code = original_lang_code_str  # Revert in-memory object
        # The cache would be reverted if the operation truly failed and we wanted to ensure
        # consistency with the DB. However, user_settings_cache is usually updated *after*
        # a successful DB operation. If DB op fails, cache isn't touched by this path.
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
    except TelegramAPIError as e_tg:
        logger.exception(
            "Telegram API error setting commands for user %s after language change: %s",
            callback_query.from_user.id,
            e_tg,
        )
        # Language is updated in DB and cache, just commands failed. Inform user.
        # The .format() method here is for constructing the user-facing message, not for logging itself.
        # So, this f-string like usage for the user message is acceptable and not a G004 violation.
        await callback_query.answer(
            new_gettext_func("Language updated, but commands might not refresh immediately. Error: {error_msg}").format(
                error_msg=str(e_tg)
            ),
            show_alert=True,
        )
        # Still try to update the menu text to the new language
        main_settings_builder = await create_main_settings_keyboard(new_gettext_func)
        main_settings_text = new_gettext_func("Settings")
        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=main_settings_text,
            reply_markup=main_settings_builder.as_markup(),
            logger_instance=logger,
            log_context="cq_set_language_ui_refresh_after_tg_error",
        )
    except Exception as e:
        logger.exception(
            "An unexpected error occurred while changing language for user %s: %s",
            callback_query.from_user.id,
            e,
        )
        # Revert if not a DB or TG specific error where partial success might be okay
        if not isinstance(e, SQLAlchemyError | TelegramAPIError):
            managed_user_settings.language_code = original_lang_code_str
            # If cache was updated optimistically before this generic exception, revert it.
            # This depends on the exact flow, but if services.user_settings_cache was updated
            # before this path, it should be reverted.
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
