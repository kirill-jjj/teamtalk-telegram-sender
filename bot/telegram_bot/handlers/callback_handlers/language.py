"""Callback query handlers for language settings."""

import gettext
import logging
from typing import TYPE_CHECKING, cast

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession  # This will be SQLAlchemyAsyncSession
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession  # SQLModel's session

from bot.core.enums import LanguageAction, SettingsNavAction
from bot.core.languages import LanguageInfo
from bot.models import UserSettings
from bot.services import _utils, user_service  # Add _utils
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
    callback_query: CallbackQuery,
    session: AsyncSession,  # Injected by DbSessionMiddleware
    user_settings: UserSettings,  # Injected by UserSettingsMiddleware
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware (as part of translator)
    callback_data: LanguageCallback,
    services: "Services",  # Injected from workflow_data
) -> None:
    """Sets the user's language preference."""
    _ = translator.gettext  # Original translator for initial messages if needed
    # Decorator ensures callback_query.message exists. We still need to check from_user and lang_code.
    if callback_data.lang_code is None:
        logger.warning("LanguageCallback received with lang_code=None for user %s", callback_query.from_user.id)
        await callback_query.answer(_("Invalid language selection."), show_alert=True)
        return

    if not callback_query.from_user:  # from_user check remains
        logger.warning("cq_set_language: callback_query.from_user is None. Callback data: %s", callback_query.data)
        # Though from_user is usually present in CallbackQuery, good to be safe.
        # The decorator doesn't cover this.
        await callback_query.answer(_("An error occurred: User information missing."), show_alert=True)
        return

    # user_settings is provided by UserSettingsMiddleware and should be session-managed or merged by the service.
    # No need to merge it here.
    new_lang_code = callback_data.lang_code
    original_lang_code = user_settings.language_code  # Use user_settings directly
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
    # The user_service.update_user_language_settings now only handles language update, not commands.
    settings_updated_successfully = await user_service.update_user_language_settings(
        cast(SQLModelAsyncSession, session), user_settings, new_lang_code, services
    )

    final_translator: gettext.GNUTranslations | gettext.NullTranslations = translator  # Default to original translator
    toast_message = ""
    toast_show_alert = False

    if not settings_updated_successfully:
        # Language update in DB/cache failed. Service layer logs details.
        # UI should reflect that language was NOT changed.
        toast_message = _("An error occurred while updating language settings. Please try again later.")
        toast_show_alert = True
        # UI will be updated with the original language settings at the end.
        # No need to revert user_settings.language_code here, as it wasn't committed.
        # The new_lang_translator should not be used.
    else:
        # Language setting in DB is updated. user_settings object might be updated by the service.
        # Use the new language's translator for subsequent messages.
        final_translator = new_lang_translator
        user_settings.language_code = new_lang_code  # Ensure in-memory model reflects change for UI

        # --- Try to update bot commands ---
        commands_updated_successfully = await _utils.update_user_bot_commands(telegram_id, new_lang_code, services)

        if commands_updated_successfully:
            toast_message = final_translator.gettext("Language updated to {lang_name}.").format(
                lang_name=selected_lang_info["native_name"]
            )
            toast_show_alert = False
        else:
            # Language updated, but commands failed. Service layer logs details.
            toast_message = final_translator.gettext(
                "Language updated, but commands might not refresh immediately. "
                "You may need to restart the chat with the bot."
            )
            toast_show_alert = True

    # --- Show combined toast message ---
    if toast_message:
        await callback_query.answer(toast_message, show_alert=toast_show_alert)
    else:  # Should not happen if logic is correct, but as a fallback
        await callback_query.answer()

    # --- Update UI (Settings Menu) using the final_translator ---
    # This will use new language if settings_updated_successfully was true, otherwise original.
    try:
        main_settings_builder = await create_main_settings_keyboard(final_translator)
        main_settings_text = final_translator.gettext("Settings")
        await safe_edit_text(
            message_to_edit=callback_query.message,  # type: ignore[arg-type]
            text=main_settings_text,
            reply_markup=main_settings_builder.as_markup(),
            logger_instance=logger,
            log_context="cq_set_language_ui_refresh",
        )
    except Exception:
        logger.exception(
            "Failed to refresh settings UI for user %s after language change attempt to %s.", telegram_id, new_lang_code
        )
        # If a toast was already shown for command failure, this additional one might be noisy.
        # However, if the primary operations seemed fine but UI failed, this is important.
        # For simplicity, show a generic UI error if it hasn't been covered by a more specific prior alert.
        if not toast_show_alert:  # Only show if a more critical alert wasn't already displayed
            await callback_query.answer(
                final_translator.gettext("Settings UI failed to refresh. Please try navigating again."), show_alert=True
            )
