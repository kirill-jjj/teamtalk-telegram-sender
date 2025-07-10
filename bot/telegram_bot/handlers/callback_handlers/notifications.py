"""Callback query handlers for notification settings."""

from __future__ import annotations

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery  # Added Message
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession  # Changed import

from bot.core.enums import NotificationAction, SettingsNavAction
from bot.models import UserSettings
from bot.services import _utils as service_utils  # Added import
from bot.telegram_bot.callback_data import NotificationActionCallback, SettingsCallback
from bot.telegram_bot.keyboards import create_notification_settings_keyboard

from ._helpers import (  # process_setting_update will be removed later
    ensure_message_context,
    safe_edit_text,
)

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
async def cq_toggle_noon_setting_action(
    callback_query: CallbackQuery,
    session: SQLModelAsyncSession,  # Changed type hint
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    _callback_data: NotificationActionCallback | None = None,  # Keep for consistent signature, though not used
    *,
    services: Services,
) -> None:
    """Handles toggling the NOON (Not On Online) setting."""
    _ = translator.gettext

    # UserSettings object from middleware is already session-managed.
    # _utils._update_user_setting_field will use this session.

    new_noon_enabled_value = not user_settings.not_on_online_enabled

    # Update the 'not_on_online_enabled' field
    # The user_settings object will be updated in-place by the helper if successful
    updated_settings_noon_toggle = await service_utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=user_settings,
        field_name="not_on_online_enabled",
        new_value=new_noon_enabled_value,
        log_context=" (user toggle NOON)",
    )

    if not updated_settings_noon_toggle:
        await callback_query.answer(_("Failed to update NOON setting. Please try again."), show_alert=True)
        # UI will not be refreshed to avoid showing potentially inconsistent state
        return

    # If NOON was enabled, also set not_on_online_confirmed to True
    # Use the 'user_settings' object which should now reflect the updated 'not_on_online_enabled' state
    final_user_settings = user_settings
    if user_settings.not_on_online_enabled and not user_settings.not_on_online_confirmed:
        confirmed_settings = await service_utils._update_user_setting_field(
            session=session,
            services=services,
            settings_to_update=user_settings,
            field_name="not_on_online_confirmed",
            new_value=True,
            log_context=" (user confirm NOON after toggle)",
        )
        if not confirmed_settings:
            logger.warning(
                "NOON setting enabled for user %s, but failed to set not_on_online_confirmed to True.",
                user_settings.telegram_id,
            )
            # The primary toggle succeeded, proceed with UI update based on that.
            # final_user_settings is already user_settings reflecting the first change.
        else:
            final_user_settings = confirmed_settings  # Both updates succeeded

    # UI Update
    new_status_display_text = _("Enabled") if final_user_settings.not_on_online_enabled else _("Disabled")
    success_toast_text = _("NOON (Not on Online) is now {status}.").format(status=new_status_display_text)
    await callback_query.answer(success_toast_text, show_alert=False)

    menu_text = _("Notification Settings")
    # final_user_settings reflects the latest state after all successful DB updates and cache updates
    updated_keyboard_markup = await create_notification_settings_keyboard(translator, final_user_settings)

    # @ensure_message_context guarantees query.message is a Message
    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=menu_text,
        reply_markup=updated_keyboard_markup.as_markup(),
        logger_instance=logger,
        log_context="cq_toggle_noon_setting_action_ui_refresh",
    )
