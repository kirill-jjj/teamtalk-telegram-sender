"""Callback query handlers for managing user subscription settings."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import F, Router

from bot.core.enums import Actor, SettingsNavAction, SubscriptionSetting
from bot.models import NotificationSetting, UserSettings
from bot.telegram_bot.callback_data import SettingsCallback, SubscriptionCallback
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import create_subscription_settings_keyboard
from bot.telegram_bot.ui_utils import safe_edit_text

if TYPE_CHECKING:
    from gettext import NullTranslations

    from aiogram.types import CallbackQuery
    from dishka.integrations.aiogram import FromDishka

    from bot.services.user_settings_service import UserSettingsService

logger = logging.getLogger(__name__)


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

    current_notification_setting = user_settings.notification_settings
    subscription_settings_markup = await create_subscription_settings_keyboard(
        translator, current_notification_setting
    )

    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Subscription Settings"),
        reply_markup=subscription_settings_markup,
    )
    await callback_query.answer()


@subscription_router.callback_query(
    SubscriptionCallback.filter(F.action == SubscriptionSetting.SET_SUB)
)
@ensure_message_context
async def set_subscription_setting(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    callback_data: SubscriptionCallback,
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    """Sets the user's subscription notification preference."""
    _ = translator.gettext
    new_setting_enum = NotificationSetting(callback_data.setting_value)

    updated_settings = await user_settings_service.update_notification_preference(
        telegram_id=callback_query.from_user.id,
        new_pref=new_setting_enum,
        actor=Actor.USER,
    )

    if not updated_settings:
        await callback_query.answer(
            _("Failed to update setting. Please try again."), show_alert=True
        )
        return

    # If the setting was not changed, updated_settings will be None, but we check above.
    # The old logic of checking if the setting is the same is now inside the service.
    await (
        callback_query.answer()
    )  # Acknowledge the press, toast is shown by service now

    setting_to_text_map = {
        NotificationSetting.ALL: _("All (Join & Leave)"),
        NotificationSetting.LEAVE_OFF: _("Join Only"),
        NotificationSetting.JOIN_OFF: _("Leave Only"),
        NotificationSetting.NONE: _("None"),
    }
    setting_display_name = setting_to_text_map.get(
        updated_settings.notification_settings, _("unknown setting")
    )
    toast_text = _("Subscription setting updated to: {setting_name}.").format(
        setting_name=setting_display_name
    )
    await callback_query.answer(toast_text)

    keyboard_markup = await create_subscription_settings_keyboard(
        translator, updated_settings.notification_settings
    )
    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Subscription Settings"),
        reply_markup=keyboard_markup,
    )
