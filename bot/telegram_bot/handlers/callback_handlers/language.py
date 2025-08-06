"""Callback query handlers for language settings."""

from collections.abc import Callable
from gettext import NullTranslations
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import Actor, LanguageChoice, SettingsNavAction
from bot.core.languages import LanguageInfo
from bot.models import UserSettings
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import LanguageCallback, SettingsCallback
from bot.telegram_bot.keyboards import create_language_selection_keyboard
from bot.telegram_bot.types.bots import EventBot

from ._helpers import ensure_message_context, safe_edit_text, with_view_refresh
from .settings_view import refresh_main_settings_view

logger = logging.getLogger(__name__)
language_router = Router(name="callback_handlers.language")


@language_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.LANGUAGE))
@ensure_message_context
async def show_language_menu(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    available_languages: FromDishka[list[LanguageInfo]],
) -> None:
    """Shows the language selection menu."""
    _ = translator.gettext
    language_markup = await create_language_selection_keyboard(translator, available_languages=available_languages)

    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Please choose your language:"),
        reply_markup=language_markup,
        logger_instance=logger,
        log_context="cq_show_language_menu",
    )


@language_router.callback_query(LanguageCallback.filter(F.action == LanguageChoice.SET_LANG))
@ensure_message_context
@with_view_refresh(refresh_main_settings_view)
async def set_language(
    query: CallbackQuery,
    user_settings: FromDishka[UserSettings],
    translator: FromDishka[NullTranslations],
    callback_data: LanguageCallback,
    bot: FromDishka[EventBot],
    translator_factory: FromDishka[Callable[[str], NullTranslations]],
    user_settings_service: FromDishka[UserSettingsService],
) -> tuple[bool, str, UserSettings | None]:
    """Sets the user's language preference and refreshes the settings view."""
    _ = translator.gettext
    new_lang_code = callback_data.lang_code

    if not new_lang_code:
        logger.warning("LanguageCallback received with lang_code=None for user %s", query.from_user.id)
        return False, _("Invalid language selection."), None

    if new_lang_code == user_settings.language_code:
        return True, "", None

    updated_settings = await user_settings_service.update_language(
        bot=bot,
        user_settings=user_settings,
        new_lang_code=new_lang_code,
        translator_factory=translator_factory,
        actor=Actor.USER,
    )

    if updated_settings:
        new_translator = translator_factory(new_lang_code)
        return True, new_translator.gettext("Language has been changed."), updated_settings
    return False, _("Failed to change language. Please try again."), None
