import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.user_settings import UserSpecificSettings
from bot.telegram_bot.keyboards import create_notification_settings_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, NotificationActionCallback
from bot.core.enums import SettingsNavAction, NotificationAction
from ._helpers import process_setting_update

logger = logging.getLogger(__name__)
notifications_router = Router(name="callback_handlers.notifications")

@notifications_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.NOTIFICATIONS))
async def cq_show_notifications_menu(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    callback_data: SettingsCallback # Consumed by filter
):
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with callback."))
        return
    await callback_query.answer()
    notification_settings_builder = create_notification_settings_keyboard(_, user_specific_settings)
    try:
        await callback_query.message.edit_text(
            text=_("Notification Settings"),
            reply_markup=notification_settings_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for notification settings menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for notification settings menu: {e}")

@notifications_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.TOGGLE_NOON))
async def cq_toggle_noon_setting_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    callback_data: NotificationActionCallback # Consumed by filter
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer(_("Error: Missing data for NOON toggle."), show_alert=True)
        return

    original_noon_status = user_specific_settings.not_on_online_enabled

    def update_logic():
        user_specific_settings.not_on_online_enabled = not original_noon_status

    def revert_logic():
        user_specific_settings.not_on_online_enabled = original_noon_status

    # Status text is for *after* the toggle
    new_status_display_text = _("Enabled") if not original_noon_status else _("Disabled")
    success_toast_text = _("NOON (Not on Online) is now {status}.").format(status=new_status_display_text)

    def refresh_ui_callable() -> tuple[str, InlineKeyboardMarkup]:
        # user_specific_settings will have the updated value due to update_logic already being called
        updated_builder = create_notification_settings_keyboard(_, user_specific_settings)
        menu_text = _("Notification Settings")
        return menu_text, updated_builder.as_markup()

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        ui_refresh_callable=refresh_ui_callable
    )
