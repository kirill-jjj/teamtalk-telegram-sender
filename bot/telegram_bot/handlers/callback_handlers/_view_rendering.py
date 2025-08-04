"""This module contains helper functions for rendering specific UI views.

Separated to prevent circular imports.
"""

import gettext
import logging
from typing import TYPE_CHECKING, cast

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.telegram_bot.keyboards import create_subscriber_action_menu_keyboard
from bot.telegram_bot.utils import format_telegram_user_display_name

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


async def _display_subscriber_view(
    query: CallbackQuery,
    target_telegram_id: int,
    page_context: int,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Helper function to display the subscriber details view."""
    _ = translator.gettext

    keyboard = await create_subscriber_action_menu_keyboard(
        translator, target_telegram_id=target_telegram_id, page=page_context
    )
    user_to_view = await session.get(UserSettings, target_telegram_id)
    display_name = str(target_telegram_id)

    active_bot = services.bot_event
    if user_to_view and user_to_view.telegram_id:
        try:
            chat_info = await active_bot.get_chat(user_to_view.telegram_id)
            display_name = format_telegram_user_display_name(chat_info)
        except TelegramAPIError:
            logger.exception("Could not fetch chat info for %s via Telegram API.", user_to_view.telegram_id)
        except Exception:
            logger.exception("Unexpected error fetching chat info for %s.", user_to_view.telegram_id)

    details_parts = [f"<b>{_('Subscriber')}: {display_name}</b>"]
    if user_to_view:
        details_parts.append(
            _("Linked TT Account: {tt_username}").format(tt_username=user_to_view.teamtalk_username or _("None"))
        )
        details_parts.append(_("Language: {lang}").format(lang=user_to_view.language_code))
        noon_status = _("Enabled") if user_to_view.not_on_online_enabled else _("Disabled")
        details_parts.append(_("NOON (Not on Online): {status}").format(status=noon_status))
        notif_setting_map = {
            NotificationSetting.ALL.value: _("All (Join & Leave)"),
            NotificationSetting.LEAVE_OFF.value: _("Join Only"),
            NotificationSetting.JOIN_OFF.value: _("Leave Only"),
            NotificationSetting.NONE.value: _("None"),
        }
        notif_setting_str = user_to_view.notification_settings.value
        details_parts.append(
            _("Notifications: {setting}").format(setting=notif_setting_map.get(notif_setting_str, notif_setting_str))
        )
        mute_mode_str = _("Blacklist") if user_to_view.mute_list_mode == MuteListMode.blacklist else _("Whitelist")
        details_parts.append(_("Mute Mode: {mode}").format(mode=mute_mode_str))
    else:
        details_parts.append(_("Subscriber settings not found."))

    text = "\n".join(details_parts)
    # This assumes query.message is a Message, which is guaranteed by @ensure_message_context
    await cast(Message, query.message).edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await query.answer()
