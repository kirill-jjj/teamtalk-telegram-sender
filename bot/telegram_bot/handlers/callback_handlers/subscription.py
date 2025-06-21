import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import UserSettings, NotificationSetting # UPDATED import
from bot.database.crud import add_subscriber, remove_subscriber
from bot.telegram_bot.keyboards import create_subscription_settings_keyboard
from bot.telegram_bot.callback_data import SettingsCallback, SubscriptionCallback
from bot.core.enums import SettingsNavAction, SubscriptionAction
from ._helpers import process_setting_update

logger = logging.getLogger(__name__)
subscription_router = Router(name="callback_handlers.subscription")

@subscription_router.callback_query(SettingsCallback.filter(F.action == SettingsNavAction.SUBSCRIPTIONS))
async def cq_show_subscriptions_menu(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings, # UPDATED
    callback_data: SettingsCallback
):
    await callback_query.answer()

    current_notification_setting = user_settings.notification_settings # UPDATED
    subscription_settings_builder = create_subscription_settings_keyboard(_, current_notification_setting)

    try:
        await callback_query.message.edit_text(
            text=_("Subscription Settings"),
            reply_markup=subscription_settings_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for subscription settings menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for subscription settings menu: {e}")

@subscription_router.callback_query(SubscriptionCallback.filter(F.action == SubscriptionAction.SET_SUB))
async def cq_set_subscription_setting(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings, # UPDATED
    callback_data: SubscriptionCallback
):
    value_to_enum_map = {
        "all": NotificationSetting.ALL,
        "leave_off": NotificationSetting.LEAVE_OFF,
        "join_off": NotificationSetting.JOIN_OFF,
        "none": NotificationSetting.NONE,
    }
    new_setting_enum = value_to_enum_map.get(callback_data.setting_value)

    if new_setting_enum is None:
        logger.error(f"Invalid subscription setting value: {callback_data.setting_value} for user {callback_query.from_user.id}")
        await callback_query.answer(_("Error: Invalid setting value received."), show_alert=True)
        return

    original_setting = user_settings.notification_settings # UPDATED

    if new_setting_enum == original_setting:
        await callback_query.answer()
        return

    def update_logic():
        user_settings.notification_settings = new_setting_enum # UPDATED

    def revert_logic():
        user_settings.notification_settings = original_setting # UPDATED

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
        user_settings=user_settings, # UPDATED
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        ui_refresh_callable=refresh_ui_callable
    )

    # After UserSettings have been successfully updated by process_setting_update
    # Manage SubscribedUser table and cache based on the change
    # No explicit success check for process_setting_update needed here, as it handles its own rollback.
    # If it failed, the original_setting and new_setting_enum would effectively be the same or reverted.

    user_id = callback_query.from_user.id

    if new_setting_enum == NotificationSetting.NONE and original_setting != NotificationSetting.NONE:
        if await remove_subscriber(session, user_id):
            logger.info(f"User {user_id} unsubscribed and removed from cache via settings change to NONE.")
        else:
            # This could happen if they were already unsubscribed for some reason, or DB error.
            logger.warning(f"User {user_id} set notifications to NONE, but failed to remove from SubscribedUser table (or already removed).")
    elif new_setting_enum != NotificationSetting.NONE and original_setting == NotificationSetting.NONE:
        if await add_subscriber(session, user_id):
            logger.info(f"User {user_id} subscribed and added to cache via settings change from NONE to {new_setting_enum.value}.")
        else:
            # This could happen if they were already subscribed for some reason, or DB error.
            logger.warning(f"User {user_id} set notifications from NONE to {new_setting_enum.value}, but failed to add to SubscribedUser table (or already added).")
