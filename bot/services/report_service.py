"""Service for generating reports."""

from gettext import NullTranslations
from html import escape

import pytalk
from pytalk.user import User as TeamTalkUser

from bot.constants import (
    WHO_CHANNEL_ID_ROOT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT2,
)
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.utils import get_tt_user_display_name
from bot.telegram_bot.models import WhoChannelGroup, WhoUser

ttstr = pytalk.instance.sdk.ttstr


def _get_user_display_channel_name(
    user_obj: TeamTalkUser, *, is_caller_admin: bool, translator: "NullTranslations"
) -> str:
    """Gets the display name of the channel a user is in."""
    channel_obj = user_obj.channel
    if not channel_obj:
        return translator.gettext("in unknown location")

    is_channel_hidden = (
        hasattr(pytalk.instance.sdk, "ChannelType")
        and (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN) != 0
    )

    server_root_ids = [
        WHO_CHANNEL_ID_ROOT,
        WHO_CHANNEL_ID_SERVER_ROOT_ALT,
        WHO_CHANNEL_ID_SERVER_ROOT_ALT2,
    ]

    if channel_obj.id in server_root_ids:
        return translator.gettext("under server")

    if is_caller_admin or not is_channel_hidden:
        return translator.gettext("in {channel_name}").format(
            channel_name=ttstr(channel_obj.name)
        )

    return translator.gettext("under server")


def _group_users_for_who_command(
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

        channel_name = _get_user_display_channel_name(
            user, is_caller_admin=is_caller_admin, translator=translator
        )
        if channel_name not in channels_data:
            channels_data[channel_name] = []

        channels_data[channel_name].append(escape(get_tt_user_display_name(user, translator)))
        user_count += 1

    return [
        WhoChannelGroup(channel_name=name, users=[WhoUser(nickname=nick) for nick in nicks])
        for name, nicks in channels_data.items()
    ], user_count


def _format_who_message(
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
            "There is {user_count} user on the server {server_host}:\n",
            "There are {user_count} users on the server {server_host}:\n",
            total_users,
        )
        if server_host
        else ngettext(
            "There is {user_count} user on the server:\n",
            "There are {user_count} users on the server:\n",
            total_users,
        )
    )
    text_reply = header_template.format(user_count=total_users, server_host=server_host)

    channel_parts = []
    for group in sorted(grouped_data, key=lambda g: g.channel_name):
        sorted_nicks = sorted(user.nickname for user in group.users)
        if not sorted_nicks:
            continue

        user_separator = translator.gettext(" and ")
        user_list = (
            f"<b>{user_separator.join(sorted_nicks)}</b>"
            if len(sorted_nicks) == 1
            else f"<b>{', '.join(sorted_nicks[:-1])}{user_separator}{sorted_nicks[-1]}</b>"
        )
        channel_parts.append(f"{user_list} {group.channel_name}")

    return text_reply + "\n" + "\n".join(channel_parts)


class ReportService:
    """Service for generating reports."""

    def get_online_users_report(
        self,
        tt_connection: TeamTalkConnection,
        *,
        is_caller_admin: bool,
        translator: NullTranslations,
    ) -> str:
        """Generates a formatted report of online users."""
        if not tt_connection.instance:
            return translator.gettext("Error: No active TeamTalk connection.")

        all_users = list(tt_connection.online_users_cache.values())
        bot_user_id = tt_connection.instance.getMyUserID()
        server_host = tt_connection.server_info.host

        grouped_data, total_users = _group_users_for_who_command(
            all_users, bot_user_id, is_caller_admin=is_caller_admin, translator=translator
        )

        return _format_who_message(
            grouped_data, total_users, translator=translator, server_host=server_host
        )
