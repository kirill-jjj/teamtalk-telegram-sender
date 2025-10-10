"""View refreshers for settings menus."""

from gettext import NullTranslations
import logging
from typing import cast

from aiogram.types import CallbackQuery, Message

from bot.services.schemas import SettingsViewDTO
from bot.telegram_bot.keyboards import (
    create_main_settings_keyboard,
    create_notification_settings_keyboard,
)
from bot.telegram_bot.ui_utils import safe_edit_text

logger = logging.getLogger(__name__)


async def refresh_main_settings_view(
    query: CallbackQuery,
    translator: NullTranslations,
    **kwargs: object,
) -> None:
    """Refreshes the main settings view."""
    _ = translator.gettext
    if not query.message:
        await query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    main_settings_builder = await create_main_settings_keyboard(translator)
    await safe_edit_text(
        message_to_edit=cast(Message, query.message),
        text=_("Settings"),
        reply_markup=main_settings_builder.as_markup(),
    )


async def refresh_notification_settings_view(
    query: CallbackQuery,
    translator: NullTranslations,
    user_settings: SettingsViewDTO,
    **kwargs: object,
) -> None:
    """Refreshes the notification settings view."""
    _ = translator.gettext
    if not query.message:
        await query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    menu_text = _("Notification Settings")
    updated_keyboard_markup = await create_notification_settings_keyboard(
        translator, user_settings
    )

    await safe_edit_text(
        message_to_edit=cast(Message, query.message),
        text=menu_text,
        reply_markup=updated_keyboard_markup.as_markup(),
    )
