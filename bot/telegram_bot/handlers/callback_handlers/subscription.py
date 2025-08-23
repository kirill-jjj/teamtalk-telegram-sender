"""Callback query handlers for managing user subscription settings."""

from __future__ import annotations

from gettext import NullTranslations
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka
from pydantic import Field, RootModel, ValidationError

from bot.core.enums import Actor, SettingsNavAction, SubscriptionSetting
from bot.database.uow import IUnitOfWork
from bot.models import NotificationSetting, UserSettings
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import SettingsCallback, SubscriptionCallback
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import create_subscription_settings_keyboard
from bot.telegram_bot.ui_utils import safe_edit_text

logger = logging.getLogger(__name__)


class SubscriptionUpdate(RootModel[NotificationSetting]):
    """Pydantic model for validating subscription update callback data."""

    root: NotificationSetting = Field(validation_alias="setting_value")


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
    await callback_query.answer()


@subscription_router.callback_query(
    SubscriptionCallback.filter(F.action == SubscriptionSetting.SET_SUB)
)
@ensure_message_context
async def set_subscription_setting(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    uow: FromDishka[IUnitOfWork],
    callback_data: SubscriptionCallback,
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    """Sets the user's subscription notification preference."""
    _ = translator.gettext
    try:
        update_data = SubscriptionUpdate.model_validate(callback_data.model_dump())
        new_setting_enum = update_data.root
    except ValidationError:
        logger.exception(
            "Invalid subscription setting value for user %s: %s",
            callback_query.from_user.id,
            callback_data.setting_value,
        )
        await callback_query.answer(_("Error: Invalid setting value."), show_alert=True)
        return

    updated_settings: UserSettings | None = None
    original_settings: UserSettings | None = None

    async with uow:
        original_settings = await uow.users.get_by_id(callback_query.from_user.id)
        if not original_settings:
            logger.warning(
                "User settings not found for user %s", callback_query.from_user.id
            )
            await callback_query.answer(_("User data not found."), show_alert=True)
            return

        if new_setting_enum == original_settings.notification_settings:
            await callback_query.answer()
            return

        updated_settings = await user_settings_service.update_notification_preference(
            user_settings=original_settings,
            new_pref=new_setting_enum,
            actor=Actor.USER,
            uow=uow,
        )

    if not updated_settings:
        await callback_query.answer(
            _("Failed to update setting. Please try again."), show_alert=True
        )
        return

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
        logger_instance=logger,
        log_context="cq_set_subscription_setting_ui_refresh",
    )
