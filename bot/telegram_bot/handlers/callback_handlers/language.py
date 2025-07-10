"""Callback query handlers for language settings."""

import gettext
import logging
from typing import TYPE_CHECKING, cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession  # This will be SQLAlchemyAsyncSession
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession  # SQLModel's session

from bot.core.enums import LanguageAction, SettingsNavAction
from bot.core.languages import LanguageInfo
from bot.models import UserSettings
from bot.services import _utils, user_service  # Add _utils
from bot.telegram_bot.callback_data import LanguageCallback, SettingsCallback
from bot.telegram_bot.keyboards import create_language_selection_keyboard, create_main_settings_keyboard

from ._helpers import safe_edit_text

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
language_router = Router(name="callback_handlers.language")


@language_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.LANGUAGE))
async def cq_show_language_menu(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    available_languages: list[LanguageInfo],
) -> None:
    """Shows the language selection menu."""
    _ = translator.gettext
    await callback_query.answer()

    # create_language_selection_keyboard now returns InlineKeyboardMarkup directly
    language_markup = await create_language_selection_keyboard(translator, available_languages=available_languages)

    if not isinstance(callback_query.message, Message):
        logger.warning(
            "cq_show_language_menu: Message is None or inaccessible for user %s. Callback data: %s",
            callback_query.from_user.id if callback_query.from_user else "Unknown",
            callback_query.data,
        )
        return

    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=_("Please choose your language:"),
        reply_markup=language_markup,  # Use the markup directly
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
) -> None:
    """Sets the user's language preference."""
    _ = translator.gettext  # Original translator for initial messages if needed
    if callback_data.lang_code is None:
        logger.warning("LanguageCallback received with lang_code=None")
        await callback_query.answer(_("Invalid language selection."), show_alert=True)
        return

    if not callback_query.message or not callback_query.from_user:
        logger.warning("cq_set_language: callback_query.message or from_user is None.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    managed_user_settings = await session.merge(user_settings)
    new_lang_code = callback_data.lang_code
    original_lang_code = managed_user_settings.language_code
    telegram_id = callback_query.from_user.id

    if new_lang_code == original_lang_code:
        await callback_query.answer()
        return

    selected_lang_info = next((lang for lang in services.available_languages if lang["code"] == new_lang_code), None)
    if not selected_lang_info:
        logger.error("Attempt to set unknown language code: %s for user %s", new_lang_code, telegram_id)
        await callback_query.answer(_("Selected language is not available."), show_alert=True)
        return

    new_lang_translator = services.get_translator(new_lang_code)

    # --- Update language settings (DB and cache) ---
    settings_updated = await user_service.update_user_language_settings(
        cast(SQLModelAsyncSession, session), managed_user_settings, new_lang_code, services
    )

    if not settings_updated:
        # Error already logged by user_service. Revert in-memory object just in case.
        managed_user_settings.language_code = original_lang_code
        await callback_query.answer(
            _("An error occurred while updating language settings. Please try again later."), show_alert=True
        )
        return

    # --- Language settings updated successfully, now update commands ---
    await callback_query.answer(
        new_lang_translator.gettext("Language updated to {lang_name}.").format(
            lang_name=selected_lang_info["native_name"]
        ),
        show_alert=False,
    )

    commands_updated = await _utils.update_user_bot_commands(telegram_id, new_lang_code, services)

    if not commands_updated:
        # Error logged by _utils. Inform user.
        await callback_query.answer(
            new_lang_translator.gettext(
                "Language updated, but commands might not refresh immediately. "
                "You may need to restart the chat with the bot."
            ),
            show_alert=True,
        )
        # Proceed to update UI anyway

    # --- Update UI (Settings Menu) ---
    try:
        main_settings_builder = await create_main_settings_keyboard(new_lang_translator)
        main_settings_text = new_lang_translator.gettext("Settings")
        if isinstance(callback_query.message, Message):
            await safe_edit_text(
                message_to_edit=callback_query.message,
                text=main_settings_text,
                reply_markup=main_settings_builder.as_markup(),
                logger_instance=logger,
                log_context="cq_set_language_ui_refresh",
            )
        else:
            logger.warning(
                "cq_set_language: Message None/inaccessible for user %s. UI not updated. CB: %s",
                callback_query.from_user.id if callback_query.from_user else "Unknown",
                callback_data.pack() if callback_data else callback_query.data,
            )
    except Exception:
        logger.exception(
            "Failed to refresh settings UI for user %s after language change to %s.", telegram_id, new_lang_code
        )
        # Don't send another alert if commands failed, as user already got one.
        # If commands succeeded but UI failed, this is the first major error user sees.
        if commands_updated:  # Only show this if commands didn't already show an error.
            # Use the gettext method from the new translator for this specific message
            await callback_query.answer(
                new_lang_translator.gettext("Language and commands updated, but UI failed to refresh."), show_alert=True
            )
