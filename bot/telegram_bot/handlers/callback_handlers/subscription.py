"""Callback query handlers for managing user subscription settings."""

from __future__ import annotations

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery  # Added Message
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.enums import SettingsNavAction, SubscriptionAction
from bot.models import NotificationSetting, UserSettings
from bot.telegram_bot.callback_data import SettingsCallback, SubscriptionCallback
from bot.telegram_bot.keyboards import create_subscription_settings_keyboard

from ._helpers import ensure_message_context, process_setting_update, safe_edit_text

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
        message_to_edit=callback_query.message, # type: ignore[arg-type]
        text=_("Subscription Settings"),
        reply_markup=subscription_settings_markup,  # Use directly
        logger_instance=logger,
        log_context="cq_show_subscriptions_menu",
    )


@subscription_router.callback_query(SubscriptionCallback.filter(F.action == SubscriptionAction.SET_SUB))
@ensure_message_context
async def cq_set_subscription_setting(
    callback_query: CallbackQuery,
    session: AsyncSession,
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
        await callback_query.answer()
        return

    def update_logic() -> None:
        user_settings.notification_settings = new_setting_enum

    def revert_logic() -> None:
        user_settings.notification_settings = original_setting

    setting_to_text_map = {
        NotificationSetting.ALL: _("All (Join & Leave)"),
        NotificationSetting.LEAVE_OFF: _("Join Only"),
        NotificationSetting.JOIN_OFF: _("Leave Only"),
        NotificationSetting.NONE: _("None"),
    }
    setting_display_name = setting_to_text_map.get(new_setting_enum, _("unknown setting"))
    success_toast_text = _("Subscription setting updated to: {setting_name}").format(setting_name=setting_display_name)

    # Prepare text and markup for UI refresh.
    # new_setting_enum (which is user_settings.notification_settings after update_logic)
    # reflects the new state for UI generation. This happens before process_setting_update commits.
    updated_markup = await create_subscription_settings_keyboard(translator, new_setting_enum)  # Renamed
    menu_text = _("Subscription Settings")

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_settings,
        translator=translator,  # Pass translator object
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        new_text=menu_text,
        new_markup=updated_markup,  # Use directly
        services=services,  # Pass services
    )
