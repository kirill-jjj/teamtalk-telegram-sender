"""Callback query handlers for language settings."""

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession  # SQLModel's session

from bot.core.enums import Actor, LanguageAction, SettingsNavAction
from bot.core.languages import LanguageInfo
from bot.models import UserSettings
from bot.services import user_service
from bot.telegram_bot.callback_data import LanguageCallback, SettingsCallback
from bot.telegram_bot.keyboards import create_language_selection_keyboard, create_main_settings_keyboard

from ._helpers import ensure_message_context, safe_edit_text

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
language_router = Router(name="callback_handlers.language")


@language_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.LANGUAGE))
@ensure_message_context
async def cq_show_language_menu(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    available_languages: list[LanguageInfo],
) -> None:
    """Shows the language selection menu."""
    _ = translator.gettext
    # Callback answering is handled by the decorator or subsequent safe_edit_text.

    # create_language_selection_keyboard now returns InlineKeyboardMarkup directly
    language_markup = await create_language_selection_keyboard(translator, available_languages=available_languages)

    # The decorator ensures callback_query.message is a Message object.
    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Please choose your language:"),
        reply_markup=language_markup,  # Use the markup directly
        logger_instance=logger,
        log_context="cq_show_language_menu",
    )


@language_router.callback_query(LanguageCallback.filter(F.action == LanguageAction.SET_LANG))
@ensure_message_context
async def cq_set_language(
    query: CallbackQuery,
    session: SQLModelAsyncSession,
    user_settings: UserSettings,
    translator: gettext.GNUTranslations,
    callback_data: LanguageCallback,
    services: "Services",
) -> None:
    """Sets the user's language preference using the refactored service function."""
    _ = translator.gettext
    new_lang_code = callback_data.lang_code

    if not new_lang_code:
        logger.warning("LanguageCallback received with lang_code=None for user %s", query.from_user.id)
        await query.answer(_("Invalid language selection."), show_alert=True)
        return

    if new_lang_code == user_settings.language_code:
        await query.answer()
        return

    # The user_service.update_language function now handles both updating the
    # language in the database and refreshing the user's bot commands.
    updated_settings = await user_service.update_language(
        session=session,
        services=services,
        user_settings=user_settings,
        new_lang_code=new_lang_code,
        actor=Actor.USER,
    )

    if updated_settings:
        new_translator = services.get_translator(new_lang_code)
        _ = new_translator.gettext
        await query.answer(_("Language has been changed."))
        # Refresh the settings menu with the new language
        main_settings_builder = await create_main_settings_keyboard(new_translator)
        await safe_edit_text(
            message_to_edit=query.message,  # type: ignore[arg-type]
            text=_("Settings"),
            reply_markup=main_settings_builder.as_markup(),
            logger_instance=logger,
            log_context="cq_set_language_ui_refresh",
        )
    else:
        await query.answer(_("Failed to change language. Please try again."), show_alert=True)
