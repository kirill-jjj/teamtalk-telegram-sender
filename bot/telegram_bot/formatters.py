"""Functions for formatting data for display."""

import gettext
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

from aiogram.types import Chat
from aiogram.utils.formatting import Bold, Text, as_list
from pytalk.user import User as TeamTalkUser

if TYPE_CHECKING:
    pass

from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.teamtalk_bot.formatters import (
    get_tt_user_display_name,
    get_user_display_channel_name,
)
from bot.telegram_bot.models import WhoChannelGroup, WhoUser

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


def group_users_for_who_command(
    users: list[TeamTalkUser],
    bot_user_id: int | None,
    *,
    is_caller_admin: bool,
    translator: "NullTranslations",
) -> tuple[list[WhoChannelGroup], int]:
    """Groups users by channel for the /who command output."""
    channels_data: dict[str, list[str]] = {}
    user_count = 0

    for user in users:
        if bot_user_id is not None and user.id == bot_user_id and not is_caller_admin:
            continue

        channel_name = get_user_display_channel_name(
            user, is_caller_admin=is_caller_admin, translator=translator
        )
        if channel_name not in channels_data:
            channels_data[channel_name] = []

        channels_data[channel_name].append(get_tt_user_display_name(user, translator))
        user_count += 1

    return [
        WhoChannelGroup(
            channel_name=name, users=[WhoUser(nickname=nick) for nick in nicks]
        )
        for name, nicks in channels_data.items()
    ], user_count


def format_who_message(
    grouped_data: list[WhoChannelGroup],
    total_users: int,
    translator: "NullTranslations",
    server_host: str | None,
) -> str:
    """Formats the final /who message string."""
    _ = translator.gettext
    ngettext = translator.ngettext

    if total_users == 0:
        return (
            _("No users found online on server {server_host}.")
            if server_host
            else _("No users found online.")
        ).format(server_host=server_host)

    header_template = (
        ngettext(
            "There is {user_count} user on the server {server_host}:",
            "There are {user_count} users on the server {server_host}:",
            total_users,
        )
        if server_host
        else ngettext(
            "There is {user_count} user on the server:",
            "There are {user_count} users on the server:",
            total_users,
        )
    )
    header = Text(
        header_template.format(user_count=total_users, server_host=server_host)
    )

    channel_parts = []
    user_separator = translator.gettext(" and ")

    for group in sorted(grouped_data, key=lambda g: g.channel_name):
        sorted_nicks = sorted(user.nickname for user in group.users)
        if not sorted_nicks:
            continue

        if len(sorted_nicks) == 1:
            user_list = Bold(sorted_nicks[0])
        else:
            # Format as: User1, User2 and User3
            user_list = Bold(
                f"{', '.join(sorted_nicks[:-1])}",
                user_separator,
                sorted_nicks[-1],
            )
        channel_parts.append(Text(user_list, " ", group.channel_name))

    # Combine header and the list of channel parts
    content = as_list(header, as_list(*channel_parts, sep="\n"), sep="\n\n")

    return content.as_html()
