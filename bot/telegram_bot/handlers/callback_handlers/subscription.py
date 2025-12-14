"""Callback query handlers for managing user subscription settings."""

from __future__ import annotations

from gettext import NullTranslations  # noqa: TC003
import logging
from typing import Annotated

from aiogram import F, Router
from aiogram.types import CallbackQuery  # noqa: TC002
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import Actor, SettingsNavAction, SubscriptionSetting
from bot.database.types import NotificationSetting
from bot.database.uow import IUnitOfWork  # noqa: TC001
from bot.services.schemas import SettingsViewDTO  # noqa: TC001
from bot.services.user_settings_service import UserSettingsService  # noqa: TC001
from bot.telegram_bot.callback_data import SettingsCallback, SubscriptionCallback
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import create_subscription_settings_keyboard
from bot.telegram_bot.ui_utils import edit_message_text

from .settings_view import refresh_subscription_settings_view

logger = logging.getLogger(__name__)


subscription_router = Router(name="callback_handlers.subscription")


@subscription_router.callback_query(
    SettingsCallback.filter(F.action == SettingsNavAction.SUBSCRIPTIONS)
)
@ensure_message_context
async def show_subscriptions_menu(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[SettingsViewDTO | None],
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
    subscription_settings_markup = create_subscription_settings_keyboard(
        translator, current_notification_setting
    )

    await edit_message_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Subscription Settings"),
        reply_markup=subscription_settings_markup,
    )


@subscription_router.callback_query(
    SubscriptionCallback.filter(F.action == SubscriptionSetting.SET_SUB)
)
@ensure_message_context
async def set_subscription_setting(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    callback_data: SubscriptionCallback,
    user_settings_service: FromDishka[UserSettingsService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Sets the user's subscription notification preference."""
    _ = translator.gettext
    new_setting_enum = NotificationSetting(callback_data.setting_value)
    telegram_id = callback_query.from_user.id
    default_lang = translator.info().get("language", "en")

    async with uow:
        result = await user_settings_service.update_notification_preference(
            uow,
            telegram_id=telegram_id,
            new_pref=new_setting_enum,
            actor=Actor.USER,
        )
        await uow.commit()

    if not result.success:
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    if result.message_key == "settings_update_no_change":
        # Nothing to do if the setting was already the same
        return

    # After a successful update, re-fetch the complete view model.
    async with uow:
        user_settings_dto = await user_settings_service.get_user_settings_view(
            uow, telegram_id, default_lang
        )

    setting_to_text_map = {
        NotificationSetting.ALL: _("All (Join & Leave)"),
        NotificationSetting.LEAVE_OFF: _("Join Only"),
        NotificationSetting.JOIN_OFF: _("Leave Only"),
        NotificationSetting.NONE: _("None"),
    }
    setting_display_name = setting_to_text_map.get(
        new_setting_enum, _("unknown setting")
    )
    toast_text = _("Subscription setting updated to: {setting_name}.").format(
        setting_name=setting_display_name
    )
    await callback_query.answer(toast_text)

    await refresh_subscription_settings_view(
        query=callback_query,
        translator=translator,
        user_settings=user_settings_dto,
    )
