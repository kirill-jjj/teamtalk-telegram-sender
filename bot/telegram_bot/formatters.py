"""Functions for formatting data for display."""

import gettext
import logging

from aiogram.types import Chat

from bot.models import MuteListMode, NotificationSetting, UserSettings

logger = logging.getLogger(__name__)


def format_telegram_user_display_name(chat: Chat | None) -> str:
    """Formats a Telegram user's display name from a Chat object.

    Returns the Telegram ID as a string if chat object is None or no other
    info is available.
    """
    if not chat:
        # This function expects a Chat object.
        # If chat is None, we cannot process it to get a display name or ID.
        return "Unknown User"

    # Default to string representation of chat.id if no other name parts are available
    display_name = str(chat.id)

    # Try to construct a more descriptive name
    full_name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
    username_part = f" (@{chat.username})" if chat.username else ""

    if full_name:
        display_name = f"{full_name}{username_part}"
    elif chat.username:  # Only username is available
        display_name = f"@{chat.username}"
    # If neither full_name nor username is present, display_name remains str(chat.id)

    return display_name


def format_subscriber_details(
    user_settings: UserSettings, display_name: str, translator: gettext.NullTranslations
) -> str:
    """Formats the detailed view of a subscriber's settings."""
    _ = translator.gettext

    details_parts = [f"<b>{_('Subscriber')}: {display_name}</b>"]
    details_parts.append(
        _("Linked TT Account: {tt_username}").format(
            tt_username=user_settings.teamtalk_username or _("None")
        )
    )
    details_parts.append(_("Language: {lang}").format(lang=user_settings.language_code))
    noon_status = _("Enabled") if user_settings.not_on_online_enabled else _("Disabled")
    details_parts.append(_("NOON (Not on Online): {status}").format(status=noon_status))
    notif_setting_map = {
        NotificationSetting.ALL.value: _("All (Join & Leave)"),
        NotificationSetting.LEAVE_OFF.value: _("Join Only"),
        NotificationSetting.JOIN_OFF.value: _("Leave Only"),
        NotificationSetting.NONE.value: _("None"),
    }
    notif_setting_str = user_settings.notification_settings.value
    details_parts.append(
        _("Notifications: {setting}").format(
            setting=notif_setting_map.get(notif_setting_str, notif_setting_str)
        )
    )
    mute_mode_str = (
        _("Blacklist")
        if user_settings.mute_list_mode == MuteListMode.blacklist
        else _("Whitelist")
    )
    details_parts.append(_("Mute Mode: {mode}").format(mode=mute_mode_str))

    return "\n".join(details_parts)
