import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_notification_settings_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, NotificationActionCallback
from bot.core.enums import SettingsNavAction, NotificationAction
from ._helpers import process_setting_update, safe_edit_text

logger = logging.getLogger(__name__)
notifications_router = Router(name="callback_handlers.notifications")

@notifications_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.NOTIFICATIONS))
async def cq_show_notifications_menu(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    callback_data: SettingsCallback
):
    await callback_query.answer()
    notification_settings_builder = create_notification_settings_keyboard(_, user_settings)
    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=_("Notification Settings"),
        reply_markup=notification_settings_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_notifications_menu"
    )

@notifications_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.TOGGLE_NOON))
async def cq_toggle_noon_setting_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    callback_data: NotificationActionCallback
):
    original_noon_status = user_settings.not_on_online_enabled

    def update_logic():
        user_settings.not_on_online_enabled = not original_noon_status

    def revert_logic():
        user_settings.not_on_online_enabled = original_noon_status

    # Status text is for *after* the toggle
    new_status_display_text = _("Enabled") if not original_noon_status else _("Disabled")
    success_toast_text = _("NOON (Not on Online) is now {status}.").format(status=new_status_display_text)

    # Подготавливаем текст и разметку здесь
    # user_settings will have the updated value here if update_logic was called before this point by process_setting_update
    # However, process_setting_update calls update_action *before* calling safe_edit_text (which uses these).
    # So, create_notification_settings_keyboard will reflect the new state.
    updated_builder = create_notification_settings_keyboard(_, user_settings)
    menu_text = _("Notification Settings")

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        new_text=menu_text,
        new_markup=updated_builder.as_markup()
    )
