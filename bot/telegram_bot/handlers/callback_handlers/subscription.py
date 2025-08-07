"""Callback query handlers for managing user subscription settings."""

from __future__ import annotations

from gettext import NullTranslations
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka
from pydantic import BaseModel, Field, ValidationError

from bot.core.enums import Actor, SettingsNavAction, SubscriptionSetting
from bot.models import NotificationSetting, UserSettings
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import SettingsCallback, SubscriptionCallback
from bot.telegram_bot.keyboards import create_subscription_settings_keyboard

from ._helpers import (
    ensure_message_context,
    safe_edit_text,
)

logger = logging.getLogger(__name__)


class SubscriptionUpdate(BaseModel):
    """Pydantic model for validating subscription update callback data."""

    setting: NotificationSetting = Field(validation_alias="setting_value")


subscription_router = Router(name="callback_handlers.subscription")


@subscription_router.callback_query(
    SettingsCallback.filter(F.action == SettingsNavAction.SUBSCRIPTIONS)
)
@ensure_message_context
async def show_subscriptions_menu(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings | None],
) -> None:
    """Shows the subscription settings menu to the user."""
    _ = translator.gettext
    if not user_settings:
        logger.warning("show_subscriptions_menu called for an event without a user.")
        await callback_query.answer(
            _("An error occurred. User data not found."), show_alert=True
        )
        return

    # Callback answering handled by decorator or safe_edit_text.

    # Decorator ensures callback_query.message is a Message object.
    current_notification_setting = user_settings.notification_settings
    subscription_settings_markup = (
        await create_subscription_settings_keyboard(  # Renamed variable
            translator, current_notification_setting
        )
    )

    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Subscription Settings"),
        reply_markup=subscription_settings_markup,  # Use directly
        logger_instance=logger,
        log_context="cq_show_subscriptions_menu",
    )


@subscription_router.callback_query(
    SubscriptionCallback.filter(F.action == SubscriptionSetting.SET_SUB)
)
@ensure_message_context
async def set_subscription_setting(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings],
    callback_data: SubscriptionCallback,
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    """Sets the user's subscription notification preference."""
    _ = translator.gettext
    try:
        update_data = SubscriptionUpdate.model_validate(callback_data.model_dump())
        new_setting_enum = update_data.setting

    except ValidationError:
        logger.exception(
            "Invalid subscription setting value received in callback for user %s. "
            "Raw value: %s",
            callback_query.from_user.id,
            callback_data.setting_value,
        )
        await callback_query.answer(
            _("Error: Invalid setting value received."), show_alert=True
        )
        return

    original_setting = user_settings.notification_settings

    if new_setting_enum == original_setting:
        await callback_query.answer()  # No change, just acknowledge.
        return

    # Call the dedicated service function to update the preference.
    # This encapsulates business logic and makes the handler cleaner.
    updated_settings = await user_settings_service.update_notification_preference(
        user_settings=user_settings,
        new_pref=new_setting_enum,
        actor=Actor.USER,
    )

    if not updated_settings:
        await callback_query.answer(
            _("Failed to update subscription setting. Please try again."),
            show_alert=True,
        )
        return

    # UI Update
    setting_to_text_map = {
        NotificationSetting.ALL: _("All (Join & Leave)"),
        NotificationSetting.LEAVE_OFF: _("Join Only"),
        NotificationSetting.JOIN_OFF: _("Leave Only"),
        NotificationSetting.NONE: _("None"),
    }
    # Use the value from updated_settings which is confirmed from DB
    setting_display_name = setting_to_text_map.get(
        updated_settings.notification_settings, _("unknown setting")
    )
    success_toast_text = _("Subscription setting updated to: {setting_name}.").format(
        setting_name=setting_display_name
    )
    await callback_query.answer(success_toast_text, show_alert=False)

    menu_text = _("Subscription Settings")
    # Use updated_settings (which is user_settings after in-place modification
    # by helper) for keyboard
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
