"""Callback query handlers for notification settings."""

from gettext import NullTranslations
import logging
from typing import Annotated

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.constants import MSG_GENERAL_ERROR
from bot.core.enums import Actor, NotificationControl, SettingsNavAction
from bot.database.uow import IUnitOfWork
from bot.services.schemas import SettingsViewDTO
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import NotificationCallback, SettingsCallback
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import create_notification_settings_keyboard
from bot.telegram_bot.ui_utils import edit_message_text

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
    user_settings: FromDishka[SettingsViewDTO | None],
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

    notification_settings_builder = create_notification_settings_keyboard(
        translator, user_settings
    )
    await edit_message_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=_("Notification Settings"),
        reply_markup=notification_settings_builder.as_markup(),
    )
    await callback_query.answer()


@notifications_router.callback_query(
    NotificationCallback.filter(F.action == NotificationControl.TOGGLE_NOON)
)
@ensure_message_context
async def toggle_noon_setting(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings_service: FromDishka[UserSettingsService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Handles toggling the NOON (Not on Online) setting."""
    _ = translator.gettext
    async with uow:
        updated_settings = await user_settings_service.toggle_noon_setting(
            uow, telegram_id=query.from_user.id, actor=Actor.USER
        )
        await uow.commit()

    if not updated_settings:
        await query.answer(
            _("Failed to update NOON setting. Please try again."), show_alert=True
        )
        return

    new_status_display_text = (
        _("Enabled") if updated_settings.not_on_online_enabled else _("Disabled")
    )
    message = _("NOON (Not on Online) is now {status}.").format(
        status=new_status_display_text
    )
    await query.answer(message)

    user_settings_dto = SettingsViewDTO(
        language_code=updated_settings.language_code,
        notification_settings=updated_settings.notification_settings,
        mute_list_mode=updated_settings.mute_list_mode,
        not_on_online_enabled=updated_settings.not_on_online_enabled,
        teamtalk_username=updated_settings.teamtalk_username,
        muted_users_count=len(updated_settings.muted_users_list),
    )
    await refresh_notification_settings_view(query, translator, user_settings_dto)
