"""Functions for formatting data for display."""

import gettext
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

from aiogram.types import Chat
from aiogram.utils.formatting import Bold, Text, as_list

if TYPE_CHECKING:
    from bot.telegram_bot.models import WhoReport

from bot.models import MuteListMode, NotificationSetting, UserSettings

logger = logging.getLogger(__name__)


def format_telegram_user_display_name(chat: Chat | None) -> str:
    """Formats a Telegram user's display name from a Chat object.

    Returns the Telegram ID as a string if chat object is None or no other
    info is available.
    """
    if not chat:
        return "Unknown User"

    display_name = str(chat.id)

    full_name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
    username_part = f" (@{chat.username})" if chat.username else ""

    if full_name:
        display_name = f"{full_name}{username_part}"
    elif chat.username:
        display_name = f"@{chat.username}"

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


def format_who_report_to_html(
    report: "WhoReport",
    translator: "NullTranslations",
) -> str:
    """Formats the final /who message string from a WhoReport object."""
    _ = translator.gettext
    ngettext = translator.ngettext

    if report.total_users == 0:
        return (
            _("No users found online on server {server_host}.")
            if report.server_name
            else _("No users found online.")
        ).format(server_host=report.server_name)

    header_template = (
        ngettext(
            "There is {user_count} user on the server {server_host}:",
            "There are {user_count} users on the server {server_host}:",
            report.total_users,
        )
        if report.server_name
        else ngettext(
            "There is {user_count} user on the server:",
            "There are {user_count} users on the server:",
            report.total_users,
        )
    )
    header = Text(
        header_template.format(
            user_count=report.total_users, server_host=report.server_name
        )
    )

    channel_parts = []
    user_separator = translator.gettext(" and ")

    for group in sorted(report.grouped_data, key=lambda g: g.channel_name):
        sorted_nicks = sorted(user.nickname for user in group.users)
        if not sorted_nicks:
            continue

        if len(sorted_nicks) == 1:
            user_list = Bold(sorted_nicks[0])
        else:
            user_list = Bold(
                f"{', '.join(sorted_nicks[:-1])}",
                user_separator,
                sorted_nicks[-1],
            )
        channel_parts.append(Text(user_list, " ", group.channel_name))

    content = as_list(header, as_list(*channel_parts, sep="\n"), sep="\n\n")

    return content.as_html()
