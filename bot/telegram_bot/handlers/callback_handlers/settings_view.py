"""View refreshers for settings menus."""

import gettext
import logging
from typing import TYPE_CHECKING, Any, cast

from aiogram.types import CallbackQuery, Message
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.telegram_bot.keyboards import create_main_settings_keyboard, create_notification_settings_keyboard
from bot.telegram_bot.ui_utils import safe_edit_text

if TYPE_CHECKING:
    from bot.models import UserSettings
    from bot.services_container import Services


logger = logging.getLogger(__name__)


async def refresh_main_settings_view(
    query: CallbackQuery,
    callback_data: Any,  # noqa: ANN401
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    **kwargs: object,
) -> None:
    """Refreshes the main settings view."""
    _ = translator.gettext
    if not query.message:
        # This should not happen if @ensure_message_context is used
        await query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    # In this specific case, the keyboard doesn't depend on user_settings
    main_settings_builder = await create_main_settings_keyboard(translator)
    await safe_edit_text(
        message_to_edit=cast(Message, query.message),
        text=_("Settings"),
        reply_markup=main_settings_builder.as_markup(),
        logger_instance=logger,
        log_context="refresh_main_settings_view",
    )


async def refresh_notification_settings_view(
    query: CallbackQuery,
    callback_data: Any,  # noqa: ANN401
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    user_settings: "UserSettings",
    **kwargs: object,
) -> None:
    """Refreshes the notification settings view."""
    _ = translator.gettext
    if not query.message:
        await query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    menu_text = _("Notification Settings")
    updated_keyboard_markup = await create_notification_settings_keyboard(translator, user_settings)

    await safe_edit_text(
        message_to_edit=cast(Message, query.message),
        text=menu_text,
        reply_markup=updated_keyboard_markup.as_markup(),
        logger_instance=logger,
        log_context="refresh_notification_settings_view",
    )
