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

from ._helpers import action_and_refresh_view, ensure_message_context, safe_edit_text
from .settings_view import refresh_main_settings_view

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
@action_and_refresh_view(refresh_main_settings_view)
async def cq_set_language(
    query: CallbackQuery,
    session: SQLModelAsyncSession,
    user_settings: UserSettings,
    translator: gettext.GNUTranslations,
    callback_data: LanguageCallback,
    services: "Services",
) -> tuple[bool, str]:
    """Sets the user's language preference and refreshes the settings view."""
    _ = translator.gettext
    new_lang_code = callback_data.lang_code

    if not new_lang_code:
        logger.warning("LanguageCallback received with lang_code=None for user %s", query.from_user.id)
        # This is a client-side error, but we can still inform the user.
        return False, _("Invalid language selection.")

    if new_lang_code == user_settings.language_code:
        # No change needed, but we don't want to show an error.
        # The decorator will handle a simple ack and refresh.
        return True, ""

    updated_settings = await user_service.update_language(
        session=session,
        services=services,
        user_settings=user_settings,
        new_lang_code=new_lang_code,
        actor=Actor.USER,
    )

    if updated_settings:
        # The message is now for the toast notification. The view is handled by the refresher.
        # We need to get the new translator to provide the correct message language.
        new_translator = services.get_translator(new_lang_code)
        return True, new_translator.gettext("Language has been changed.")
    # Return a failure message if the update fails.
    return False, _("Failed to change language. Please try again.")
