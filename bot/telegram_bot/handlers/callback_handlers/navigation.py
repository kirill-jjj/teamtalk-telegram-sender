"""Callback query handlers for navigating back in settings menus."""

from gettext import NullTranslations
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SettingsNavAction
from bot.telegram_bot.callback_data import SettingsCallback
from bot.telegram_bot.keyboards import create_main_settings_keyboard

from ._helpers import ensure_message_context, safe_edit_text

logger = logging.getLogger(__name__)
navigation_router = Router(name="callback_handlers.navigation")


@navigation_router.callback_query(
    SettingsCallback.filter(F.action == SettingsNavAction.BACK_TO_MAIN)
)
@ensure_message_context
async def back_to_main_settings_menu(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
) -> None:
    """Handles navigating back to the main settings menu."""
    _ = translator.gettext
    main_settings_builder = await create_main_settings_keyboard(translator)
    main_settings_text = _("Settings")

    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=main_settings_text,
        reply_markup=main_settings_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_back_to_main_settings_menu",
    )
