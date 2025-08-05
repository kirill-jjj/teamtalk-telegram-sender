"""Callback query handlers for notification settings."""

from __future__ import annotations

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from bot.core.enums import Actor, NotificationAction, SettingsNavAction
from bot.models import UserSettings
from bot.services import user_service
from bot.telegram_bot.callback_data import NotificationActionCallback, SettingsCallback
from bot.telegram_bot.keyboards import create_notification_settings_keyboard

from ._helpers import action_and_refresh_view, ensure_message_context, safe_edit_text
from .settings_view import refresh_notification_settings_view

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
notifications_router = Router(name="callback_handlers.notifications")


@notifications_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.NOTIFICATIONS))
@ensure_message_context
async def cq_show_notifications_menu(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    _callback_data: SettingsCallback | None = None,  # Keep for consistent signature, though not used
) -> None:
    """Shows the notification settings menu."""
    _ = translator.gettext
    # Callback answering handled by decorator or safe_edit_text.

    # Decorator ensures callback_query.message is a Message object.
    notification_settings_builder = await create_notification_settings_keyboard(translator, user_settings)
    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Notification Settings"),
        reply_markup=notification_settings_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_notifications_menu",
    )


@notifications_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.TOGGLE_NOON))
@ensure_message_context
@action_and_refresh_view(refresh_notification_settings_view)
async def cq_toggle_noon_setting_action(
    callback_query: CallbackQuery,
    session: SQLModelAsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    services: Services,
    **kwargs,
) -> tuple[bool, str]:
    """Handles toggling the NOON (Not On Online) setting."""
    _ = translator.gettext

    updated_settings = await user_service.update_noon_setting(
        session=session,
        services=services,
        user_settings=user_settings,
        actor=Actor.USER,
    )

    if not updated_settings:
        return False, _("Failed to update NOON setting. Please try again.")

    new_status_display_text = _("Enabled") if updated_settings.not_on_online_enabled else _("Disabled")
    return True, _("NOON (Not on Online) is now {status}.").format(status=new_status_display_text)
