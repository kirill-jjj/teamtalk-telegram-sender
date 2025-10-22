"""Functions for formatting data for display."""

import gettext
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

from aiogram import html
from aiogram.types import Chat
from aiogram.utils.formatting import Bold, Text, as_list

if TYPE_CHECKING:
    from bot.telegram_bot.models import WhoReport

from bot.core.enums import AdminCommand
from bot.models import MuteListMode, NotificationSetting
from bot.services.schemas import SettingsViewDTO

logger = logging.getLogger(__name__)


def format_mute_toast(
    username_to_toggle: str,
    *,
    was_added_to_list: bool,
    current_mode: MuteListMode,
    translator: NullTranslations,
) -> str:
    """Formats the toast message for a mute/unmute action."""
    _ = translator.gettext
    clean_username = username_to_toggle.strip("<>")
    quoted_username = html.quote(clean_username)
    action_key_map = {
        (MuteListMode.blacklist, True): _("added to blacklist"),
        (MuteListMode.blacklist, False): _("removed from blacklist"),
        (MuteListMode.whitelist, True): _("added to whitelist"),
        (MuteListMode.whitelist, False): _("removed from whitelist"),
    }
    action_text = action_key_map[current_mode, was_added_to_list]
    return _("{username} has been {action}.").format(
        username=quoted_username, action=action_text
    )


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
    user_settings: SettingsViewDTO,
    display_name: str,
    translator: gettext.NullTranslations,
) -> str:
    """Formats the detailed view of a subscriber's settings."""
    _ = translator.gettext

    translated_subscriber_line = _("Subscriber: {display_name}").format(
        display_name=display_name
    )
    noon_status = _("Enabled") if user_settings.not_on_online_enabled else _("Disabled")
    details_parts = [f"<b>{translated_subscriber_line}</b>"]
    details_parts.extend(
        [
            _("Linked TT Account: {tt_username}").format(
                tt_username=user_settings.teamtalk_username or _("None")
            ),
            _("Language: {lang}").format(lang=user_settings.language_code),
            _("NOON (Not on Online): {status}").format(status=noon_status),
        ]
    )
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
    report_dto: "WhoReport",
    translator: "NullTranslations",
) -> str:
    """Formats the final /who message string from a WhoReport DTO."""
    _ = translator.gettext
    ngettext = translator.ngettext

    if report_dto.error_message:
        return report_dto.error_message

    if not report_dto.payload or report_dto.payload.total_users == 0:
        return (
            _("No users found online on server {server_host}.")
            if report_dto.payload and report_dto.payload.server_name
            else _("No users found online.")
        ).format(
            server_host=report_dto.payload.server_name if report_dto.payload else ""
        )

    report = report_dto.payload
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


def format_help_text(translator: NullTranslations, *, is_admin: bool) -> str:
    """Builds the help message for Telegram users."""
    _ = translator.gettext
    parts = [
        _("<b>Available Commands:</b>"),
        _(
            "/who - Show online users.\n"
            "/settings - Access the interactive settings menu "
            "(language, notifications, mute lists, NOON feature).\n"
            "/help - Show this help message.\n"
            "(Note: `/start` is used to initiate the bot and process deeplinks.)"
        ),
    ]
    if is_admin:
        parts.extend(
            [
                _("\n<b>Admin Commands:</b>"),
                _(
                    "/kick - Kick a user from the server (via buttons).\n"
                    "/ban - Ban a user from the server (via buttons).\n"
                    "/unban - Unban a user from the server "
                    "(shows a list of banned users).\n"
                    "/subscribers - View and manage subscribed users."
                ),
            ]
        )
    return "\n".join(parts)


def format_moderation_prompt(
    command: "AdminCommand",
    server_name: str,
    translator: NullTranslations,
) -> str:
    """Formats the prompt for a moderation action (kick/ban)."""
    _ = translator.gettext
    command_text_map = {
        "kick": _("Select a user to kick from {server_host}:").format(
            server_host=server_name
        ),
        "ban": _("Select a user to ban from {server_host}:").format(
            server_host=server_name
        ),
    }
    return command_text_map.get(command.value, _("Select a user:"))


def format_manage_muted_menu_text(
    translator: NullTranslations,
    mute_list_mode: MuteListMode,
) -> str:
    """Formats the text for the mute management menu."""
    _ = translator.gettext
    if mute_list_mode == MuteListMode.blacklist:
        current_mode_text = _(
            "Current mode is Blacklist. You receive notifications from everyone "
            "except those on the list."
        )
    else:
        current_mode_text = _(
            "Current mode is Whitelist. You only receive notifications "
            "from users on the list."
        )
    return _("Manage Mute List\n\n{current_mode_description}").format(
        current_mode_description=current_mode_text
    )


def format_paginated_list_text(
    translator: NullTranslations,
    title_text: str,
    total_items: int,
    page: int,
    page_size: int,
    empty_list_text: str,
    server_host_for_display: str | None = None,
) -> str:
    """Constructs the text part of a message for a paginated list."""
    _ = translator.gettext
    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    current_page_idx = max(0, min(page, total_pages - 1))

    message_parts = [title_text]
    if total_items == 0:
        message_parts.append(empty_list_text)

    page_indicator_text = _("Page {current_page}/{total_pages}").format(
        current_page=current_page_idx + 1, total_pages=total_pages
    )

    if server_host_for_display and " on {server_host}" not in message_parts[0]:
        message_parts[0] += _(" on {server_host}").format(
            server_host=server_host_for_display
        )

    message_parts.append(f"\n{page_indicator_text}")
    return "\n".join(message_parts)
