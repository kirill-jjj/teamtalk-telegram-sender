"""Callback query handlers for notification settings."""

from __future__ import annotations

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message  # Added Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.enums import NotificationAction, SettingsNavAction
from bot.core.user_settings import update_user_settings_in_db
from bot.models import UserSettings
from bot.telegram_bot.callback_data import NotificationActionCallback, SettingsCallback
from bot.telegram_bot.keyboards import create_notification_settings_keyboard

from ._helpers import safe_edit_text

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
notifications_router = Router(name="callback_handlers.notifications")


@notifications_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.NOTIFICATIONS))
async def cq_show_notifications_menu(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    _callback_data: SettingsCallback | None = None,  # Keep for consistent signature, though not used
) -> None:
    """Shows the notification settings menu."""
    _ = translator.gettext
    await callback_query.answer()

    if not isinstance(callback_query.message, Message):
        logger.warning(
            "cq_show_notifications_menu: Message is None or inaccessible for user %s. Callback data: %s",
            callback_query.from_user.id if callback_query.from_user else "Unknown",
            _callback_data.pack() if _callback_data else callback_query.data,
        )
        return

    notification_settings_builder = await create_notification_settings_keyboard(translator, user_settings)
    await safe_edit_text(
        message_to_edit=callback_query.message,  # Now known to be Message
        text=_("Notification Settings"),
        reply_markup=notification_settings_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_notifications_menu",
    )


@notifications_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.TOGGLE_NOON))
async def cq_toggle_noon_setting_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    _callback_data: NotificationActionCallback | None = None,  # Keep for consistent signature, though not used
    *,
    services: Services,
) -> None:
    """Handles toggling the NOON (Not On Online) setting."""
    _ = translator.gettext
    if not callback_query.message:
        logger.warning("cq_toggle_noon_setting_action: Callback query is missing message.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    original_noon_status = user_settings.not_on_online_enabled
    user_settings.not_on_online_enabled = not original_noon_status

    if not await update_user_settings_in_db(session, user_settings):
        user_settings.not_on_online_enabled = original_noon_status  # Revert in-memory change
        await callback_query.answer(_("An error occurred while saving. Please try again."), show_alert=True)
        return

    services.cache.update_user_settings(user_settings)  # Use CacheService
    logger.debug(
        "NOON setting for user %s toggled to %s and saved to DB/cache via CacheService.",
        user_settings.telegram_id,
        user_settings.not_on_online_enabled,
    )

    new_status_display_text = _("Enabled") if user_settings.not_on_online_enabled else _("Disabled")
    success_toast_text = _("NOON (Not on Online) is now {status}.").format(status=new_status_display_text)

    updated_builder = await create_notification_settings_keyboard(translator, user_settings)
    menu_text = _("Notification Settings")

    await callback_query.answer(success_toast_text)

    if not isinstance(callback_query.message, Message):  # Check if message is valid
        logger.warning(
            "cq_toggle_noon_setting_action: Message is None or inaccessible for user %s after NOON toggle. "
            "Settings updated, but UI may not refresh. Callback data: %s",
            callback_query.from_user.id if callback_query.from_user else "Unknown",
            _callback_data.pack() if _callback_data else callback_query.data,
        )
        return

    await safe_edit_text(
        message_to_edit=callback_query.message,  # Now known to be Message
        text=menu_text,
        reply_markup=updated_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_toggle_noon_setting_action",
    )
