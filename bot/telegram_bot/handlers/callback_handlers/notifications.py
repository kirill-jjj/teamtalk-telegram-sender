"""Callback query handlers for notification settings."""

from gettext import NullTranslations
import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.callback_answer import CallbackAnswer
from dishka.integrations.aiogram import FromDishka

from bot.constants import MSG_GENERAL_ERROR
from bot.core.enums import Actor, NotificationControl, SettingsNavAction
from bot.models import UserSettings
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import NotificationCallback, SettingsCallback
from bot.telegram_bot.keyboards import create_notification_settings_keyboard

from bot.telegram_bot.handlers.decorators import (
    ensure_message_context,
    with_view_refresh,
)
from bot.telegram_bot.ui_utils import safe_edit_text
from .settings_view import refresh_notification_settings_view

logger = logging.getLogger(__name__)
notifications_router = Router(name="callback_handlers.notifications")


@notifications_router.callback_query(
    SettingsCallback.filter(F.action == SettingsNavAction.NOTIFICATIONS)
)
@ensure_message_context
async def show_notifications_menu(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings | None],
) -> None:
    """Shows the notification settings menu."""
    _ = translator.gettext
    if not user_settings:
        logger.warning(
            "Cannot show notifications menu for event without a user, "
            "user_settings is None."
        )
        await callback_query.answer(_(MSG_GENERAL_ERROR), show_alert=True)
        return

    notification_settings_builder = await create_notification_settings_keyboard(
        translator, user_settings
    )
    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Notification Settings"),
        reply_markup=notification_settings_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_notifications_menu",
    )


@notifications_router.callback_query(
    NotificationCallback.filter(F.action == NotificationControl.TOGGLE_NOON)
)
@ensure_message_context
@with_view_refresh(refresh_notification_settings_view)
async def toggle_noon_setting(
    query: CallbackQuery,
    callback_answer: CallbackAnswer,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings],
    user_settings_service: FromDishka[UserSettingsService],
    **kwargs: Any,  # noqa: ANN401
) -> tuple[bool, str, UserSettings | None]:
    """Handles toggling the NOON (Not On Online) setting."""
    _ = translator.gettext

    updated_settings = await user_settings_service.toggle_noon_setting(
        user_settings=user_settings, actor=Actor.USER
    )

    if not updated_settings:
        return False, _("Failed to update NOON setting. Please try again."), None

    new_status_display_text = (
        _("Enabled") if updated_settings.not_on_online_enabled else _("Disabled")
    )
    message = _("NOON (Not on Online) is now {status}.").format(
        status=new_status_display_text
    )

    return True, message, updated_settings
