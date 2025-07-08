"""Callback query handlers for navigating back in settings menus."""

import gettext
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.core.enums import SettingsNavAction
from bot.telegram_bot.callback_data import SettingsCallback
from bot.telegram_bot.keyboards import create_main_settings_keyboard

from ._helpers import safe_edit_text

logger = logging.getLogger(__name__)
navigation_router = Router(name="callback_handlers.navigation")


@navigation_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.BACK_TO_MAIN))
async def cq_back_to_main_settings_menu(
    callback_query: CallbackQuery, translator: gettext.GNUTranslations, callback_data: SettingsCallback
):
    """Handles navigating back to the main settings menu."""
    _ = translator.gettext
    await callback_query.answer()

    main_settings_builder = await create_main_settings_keyboard(translator)
    main_settings_text = _("Settings")

    if callback_query.message:
        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=main_settings_text,
            reply_markup=main_settings_builder.as_markup(),
            logger_instance=logger,
            log_context="cq_back_to_main_settings_menu",
        )
