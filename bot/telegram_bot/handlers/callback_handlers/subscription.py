import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, ValidationError

from bot.models import UserSettings, NotificationSetting
from bot.telegram_bot.keyboards import create_subscription_settings_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, SubscriptionCallback
from bot.core.enums import SettingsNavAction, SubscriptionAction
from ._helpers import process_setting_update, safe_edit_text

logger = logging.getLogger(__name__)


class SubscriptionUpdate(BaseModel):
    setting: NotificationSetting = Field(validation_alias='setting_value')


subscription_router = Router(name="callback_handlers.subscription")

@subscription_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.SUBSCRIPTIONS))
async def cq_show_subscriptions_menu(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    callback_data: SettingsCallback
):
    await callback_query.answer()

    current_notification_setting = user_settings.notification_settings
    subscription_settings_builder = create_subscription_settings_keyboard(_, current_notification_setting)

    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=_("Subscription Settings"),
        reply_markup=subscription_settings_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_subscriptions_menu"
    )

@subscription_router.callback_query(SubscriptionCallback.filter(F.action == SubscriptionAction.SET_SUB))
async def cq_set_subscription_setting(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    callback_data: SubscriptionCallback
):
    try:
        update_data = SubscriptionUpdate.model_validate(callback_data.model_dump())
        new_setting_enum = update_data.setting

    except ValidationError as e:
        logger.error(f"Invalid subscription setting value received in callback: {e} for user {callback_query.from_user.id}. Raw value: {callback_data.setting_value}")
        await callback_query.answer(_("Error: Invalid setting value received."), show_alert=True)
        return

    original_setting = user_settings.notification_settings

    if new_setting_enum == original_setting:
        await callback_query.answer()
        return

    def update_logic():
        user_settings.notification_settings = new_setting_enum

    def revert_logic():
        user_settings.notification_settings = original_setting

    setting_to_text_map = {
        NotificationSetting.ALL: _("All (Join & Leave)"),
        NotificationSetting.LEAVE_OFF: _("Join Only"),
        NotificationSetting.JOIN_OFF: _("Leave Only"),
        NotificationSetting.NONE: _("None"),
    }
    setting_display_name = setting_to_text_map.get(new_setting_enum, _("unknown setting"))
    success_toast_text = _("Subscription setting updated to: {setting_name}").format(setting_name=setting_display_name)

    def refresh_ui_callable() -> tuple[str, InlineKeyboardMarkup]:
        updated_builder = create_subscription_settings_keyboard(_, new_setting_enum)
        menu_text = _("Subscription Settings")
        return menu_text, updated_builder.as_markup()

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        ui_refresh_callable=refresh_ui_callable
    )
