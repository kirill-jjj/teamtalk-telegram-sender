"""Callback query handlers for managing user subscription settings."""

from __future__ import annotations

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery
from pydantic import BaseModel, Field, ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from bot.core.enums import SettingsNavAction, SubscriptionAction
from bot.models import NotificationSetting, UserSettings
from bot.services import _utils as service_utils
from bot.telegram_bot.callback_data import SettingsCallback, SubscriptionCallback
from bot.telegram_bot.keyboards import create_subscription_settings_keyboard

from ._helpers import (
    ensure_message_context,
    safe_edit_text,
)

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


class SubscriptionUpdate(BaseModel):
    """Pydantic model for validating subscription update callback data."""

    setting: NotificationSetting = Field(validation_alias="setting_value")


subscription_router = Router(name="callback_handlers.subscription")


@subscription_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.SUBSCRIPTIONS))
@ensure_message_context
async def cq_show_subscriptions_menu(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    _callback_data: SettingsCallback | None = None,  # Prefixed
) -> None:
    """Shows the subscription settings menu to the user."""
    _ = translator.gettext
    # Callback answering handled by decorator or safe_edit_text.

    # Decorator ensures callback_query.message is a Message object.
    current_notification_setting = user_settings.notification_settings
    subscription_settings_markup = await create_subscription_settings_keyboard(  # Renamed variable
        translator, current_notification_setting
    )

    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Subscription Settings"),
        reply_markup=subscription_settings_markup,  # Use directly
        logger_instance=logger,
        log_context="cq_show_subscriptions_menu",
    )


@subscription_router.callback_query(SubscriptionCallback.filter(F.action == SubscriptionAction.SET_SUB))
@ensure_message_context
async def cq_set_subscription_setting(
    callback_query: CallbackQuery,
    session: SQLModelAsyncSession,  # Changed type hint
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: SubscriptionCallback,
    services: Services,
) -> None:
    """Sets the user's subscription notification preference."""
    _ = translator.gettext
    try:
        update_data = SubscriptionUpdate.model_validate(callback_data.model_dump())
        new_setting_enum = update_data.setting

    except ValidationError:
        logger.exception(
            "Invalid subscription setting value received in callback for user %s. Raw value: %s",
            callback_query.from_user.id,
            callback_data.setting_value,
        )
        await callback_query.answer(_("Error: Invalid setting value received."), show_alert=True)
        return

    original_setting = user_settings.notification_settings

    if new_setting_enum == original_setting:
        await callback_query.answer()  # No change, just acknowledge.
        return

    # Call the generic helper to update the field
    # user_settings object from middleware is already session-managed.
    updated_settings = await service_utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=user_settings,
        field_name="notification_settings",
        new_value=new_setting_enum,
        log_context=" (user set subscription)",
    )

    if not updated_settings:
        await callback_query.answer(_("Failed to update subscription setting. Please try again."), show_alert=True)
        return

    # UI Update
    setting_to_text_map = {
        NotificationSetting.ALL: _("All (Join & Leave)"),
        NotificationSetting.LEAVE_OFF: _("Join Only"),
        NotificationSetting.JOIN_OFF: _("Leave Only"),
        NotificationSetting.NONE: _("None"),
    }
    # Use the value from updated_settings which is confirmed from DB
    setting_display_name = setting_to_text_map.get(updated_settings.notification_settings, _("unknown setting"))
    success_toast_text = _("Subscription setting updated to: {setting_name}.").format(setting_name=setting_display_name)
    await callback_query.answer(success_toast_text, show_alert=False)

    menu_text = _("Subscription Settings")
    # Use updated_settings (which is user_settings after in-place modification by helper) for keyboard
    updated_keyboard_markup = await create_subscription_settings_keyboard(
        translator, updated_settings.notification_settings
    )

    # @ensure_message_context guarantees query.message is a Message
    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=menu_text,
        reply_markup=updated_keyboard_markup,  # Use directly
        logger_instance=logger,
        log_context="cq_set_subscription_setting_ui_refresh",
    )
