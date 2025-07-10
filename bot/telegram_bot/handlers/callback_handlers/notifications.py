"""Callback query handlers for notification settings."""

from __future__ import annotations

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message  # Added Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.enums import NotificationAction, SettingsNavAction
from bot.models import UserSettings
from bot.telegram_bot.callback_data import NotificationActionCallback, SettingsCallback
from bot.telegram_bot.keyboards import create_notification_settings_keyboard

from ._helpers import process_setting_update, safe_edit_text

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

    # Store original states for potential revert
    original_noon_enabled = user_settings.not_on_online_enabled
    original_noon_confirmed = user_settings.not_on_online_confirmed

    # Determine the new state first to generate UI elements correctly
    new_noon_enabled_state = not original_noon_enabled

    def update_noon_action() -> None:
        user_settings.not_on_online_enabled = new_noon_enabled_state
        if new_noon_enabled_state: # If NOON is being enabled
            user_settings.not_on_online_confirmed = True
        # If NOON is being disabled, not_on_online_confirmed remains as is,
        # as per current logic in admin_service (it's only set to True on enable).
        # However, for a toggle, it might be more consistent to also handle this.
        # For now, sticking to mimicking existing explicit logic.

    def revert_noon_action() -> None:
        user_settings.not_on_online_enabled = original_noon_enabled
        user_settings.not_on_online_confirmed = original_noon_confirmed

    # --- Prepare parameters for process_setting_update ---

    # 1. Perform the update action in memory to get the correct state for UI elements
    update_noon_action()

    # 2. Generate UI elements based on the new state
    new_status_display_text = _("Enabled") if user_settings.not_on_online_enabled else _("Disabled")
    success_toast_text = _("NOON (Not on Online) is now {status}.").format(status=new_status_display_text)

    menu_text = _("Notification Settings")
    updated_keyboard = await create_notification_settings_keyboard(translator, user_settings)

    # 3. Call the helper
    # The update_action is already performed, but process_setting_update expects it.
    # We pass the same update_noon_action. If process_setting_update calls it again,
    # it should be idempotent or the state should be correctly set.
    # Given new_noon_enabled_state is fixed, it will be idempotent.
    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_settings,
        translator=translator,
        update_action=update_noon_action, # This will effectively re-apply the state
        revert_action=revert_noon_action,
        success_toast_text=success_toast_text,
        new_text=menu_text,
        new_markup=updated_keyboard.as_markup(),
        services=services,
    )
