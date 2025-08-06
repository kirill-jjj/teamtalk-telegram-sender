"""Callback query handlers for notification settings."""

from gettext import GNUTranslations
import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import Actor, NotificationControl, SettingsNavAction
from bot.models import UserSettings
from bot.services import user_service
from bot.services.cache_service import CacheService
from bot.telegram_bot.callback_data import NotificationCallback, SettingsCallback
from bot.telegram_bot.keyboards import create_notification_settings_keyboard

from ._helpers import ensure_message_context, safe_edit_text, with_view_refresh
from .settings_view import refresh_notification_settings_view

logger = logging.getLogger(__name__)
notifications_router = Router(name="callback_handlers.notifications")


@notifications_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.NOTIFICATIONS))
@ensure_message_context
async def show_notifications_menu(
    callback_query: CallbackQuery,
    translator: FromDishka[GNUTranslations],
    user_settings: FromDishka[UserSettings],
) -> None:
    """Shows the notification settings menu."""
    _ = translator.gettext
    notification_settings_builder = await create_notification_settings_keyboard(translator, user_settings)
    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=_("Notification Settings"),
        reply_markup=notification_settings_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_notifications_menu",
    )


@notifications_router.callback_query(NotificationCallback.filter(F.action == NotificationControl.TOGGLE_NOON))
@ensure_message_context
@with_view_refresh(refresh_notification_settings_view)
async def toggle_noon_setting(
    session: FromDishka[AsyncSession],
    translator: FromDishka[GNUTranslations],
    user_settings: FromDishka[UserSettings],
    cache: FromDishka[CacheService],
    **kwargs: Any,
) -> tuple[bool, str]:
    """Handles toggling the NOON (Not On Online) setting."""
    _ = translator.gettext

    updated_settings = await user_service.update_noon_setting(
        session=session,
        cache=cache,
        user_settings=user_settings,
        actor=Actor.USER,
    )

    if not updated_settings:
        return False, _("Failed to update NOON setting. Please try again.")

    new_status_display_text = _("Enabled") if updated_settings.not_on_online_enabled else _("Disabled")
    return True, _("NOON (Not on Online) is now {status}.").format(status=new_status_display_text)
