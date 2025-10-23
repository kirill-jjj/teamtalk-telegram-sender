"""Functions for formatting data for display."""

import gettext
from gettext import NullTranslations
import logging

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser

from bot.config import Settings
from bot.constants import (
    WHO_CHANNEL_ID_ROOT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT2,
)
from bot.core.enums import DeeplinkAction
from bot.models import Deeplink as DeeplinkModel
from bot.services.schemas import AdminManagementResult

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def format_deeplink_reply(
    deeplink: DeeplinkModel,
    bot_username: str,
    translator: NullTranslations,
) -> str:
    """Formats the reply text with the deeplink URL."""
    _ = translator.gettext
    deeplink_url = f"https://t.me/{bot_username}?start={deeplink.token}"

    reply_text_map = {
        DeeplinkAction.SUBSCRIBE: _(
            "Click this link to subscribe to notifications "
            "(link valid for 5 minutes):\n{deeplink_url}"
        ),
        DeeplinkAction.UNSUBSCRIBE: _(
            "Click this link to unsubscribe from notifications "
            "(link valid for 5 minutes):\n{deeplink_url}"
        ),
    }
    template = reply_text_map.get(deeplink.action, "Invalid action for deeplink.")
    return template.format(deeplink_url=deeplink_url)


logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def format_admin_management_result(
    result: AdminManagementResult, translator: NullTranslations
) -> str:
    """Formats the result of an admin management operation into a reply string."""
    _ = translator.gettext
    response_parts = result.error_messages[:]

    if result.add_result.successful_ids:
        response_parts.append(
            _("Successfully added {} admins.").format(
                len(result.add_result.successful_ids)
            )
        )
    if result.add_result.failed_ids:
        response_parts.append(
            _("Failed to add {} admins (already admins or invalid IDs).").format(
                len(result.add_result.failed_ids)
            )
        )
    if result.remove_result.successful_ids:
        response_parts.append(
            _("Successfully removed {} admins.").format(
                len(result.remove_result.successful_ids)
            )
        )
    if result.remove_result.failed_ids:
        response_parts.append(
            _("Failed to remove {} admins (not admins or invalid IDs).").format(
                len(result.remove_result.failed_ids)
            )
        )

    return (
        "\n".join(response_parts)
        if response_parts
        else _("No valid admin IDs provided for adding or removing.")
    )


def _split_text_for_tt(text: str, max_len_bytes: int) -> list[str]:
    """Splits a long text message into parts suitable for TeamTalk."""
    parts_to_send_list = []
    remaining_text = text

    while remaining_text:
        if len(remaining_text.encode("utf-8", errors="ignore")) <= max_len_bytes:
            parts_to_send_list.append(remaining_text)
            break

        current_chunk_str = ""
        current_chunk_bytes_len = 0
        last_safe_split_index_in_chunk = -1
        last_safe_split_index_in_remaining = -1

        for i, char_code in enumerate(remaining_text):
            char_bytes = char_code.encode("utf-8", errors="ignore")
            char_bytes_len = len(char_bytes)

            if current_chunk_bytes_len + char_bytes_len > max_len_bytes:
                if last_safe_split_index_in_chunk != -1:
                    parts_to_send_list.append(
                        current_chunk_str[:last_safe_split_index_in_chunk]
                    )
                    remaining_text = remaining_text[
                        last_safe_split_index_in_remaining:
                    ].lstrip()
                else:
                    parts_to_send_list.append(current_chunk_str)
                    remaining_text = remaining_text[i:].lstrip()
                break

            current_chunk_str += char_code
            current_chunk_bytes_len += char_bytes_len

            if char_code in {"\n", " "}:
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1

            if i == len(remaining_text) - 1:
                parts_to_send_list.append(current_chunk_str)
                remaining_text = ""
                break
        else:
            if current_chunk_str and not remaining_text:
                pass
            remaining_text = ""
    return parts_to_send_list


def get_server_display_name(
    tt_instance: TeamTalkInstance | None,
    translator: gettext.NullTranslations,
    app_cfg: Settings,
) -> str:
    """Determines the server name to display.

    It prioritizes the server name from `app_cfg.teamtalk.server_name`.
    If not set, it attempts to fetch it from the TeamTalk instance.
    Falls back to "Unknown Server" if unavailable.
    """
    _ = translator.gettext

    # Prioritize the server name from app_cfg.teamtalk.server_name
    if app_cfg.teamtalk.server_name:
        return app_cfg.teamtalk.server_name

    # If not set in config, attempt to fetch it from the TeamTalk instance
    server_name_from_instance: str | None = None
    if tt_instance and tt_instance.connected:
        try:
            server_name_from_instance = ttstr(
                tt_instance.server.get_properties().server_name
            )
        except (TimeoutError, pytalk.exceptions.TeamTalkException, Exception):
            logger.exception(
                "Error getting server name from TT instance %s.",
                tt_instance.server_info.host if tt_instance.server_info else "N/A",
            )

    if server_name_from_instance:
        return server_name_from_instance

    # Fallback
    return _("Unknown Server")


def get_tt_user_display_name(
    user: TeamTalkUser, translator: gettext.NullTranslations
) -> str:
    """Gets a display-friendly name for a TeamTalk user.

    Prioritizes nickname, then username. Falls back to a localized "unknown user".

    Args:
        user: The TeamTalkUser object.
        translator: The gettext translator object (can be NullTranslations).

    Returns:
        The display name string.
    """
    _ = translator.gettext
    display_name = str(ttstr(user.nickname))
    if not display_name:
        display_name = str(ttstr(user.username))
    if not display_name:
        display_name = _("unknown user")
    return display_name


def get_user_display_channel_name(
    user_obj: TeamTalkUser, *, is_caller_admin: bool, translator: "NullTranslations"
) -> str:
    """Gets the display name of the channel a user is in."""
    channel_obj = user_obj.channel
    if not channel_obj:
        return translator.gettext("in unknown location")

    is_channel_hidden = (
        hasattr(pytalk.instance.sdk, "ChannelType")
        and (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN)
        != 0
    )

    server_root_ids = [
        WHO_CHANNEL_ID_SERVER_ROOT_ALT,
        WHO_CHANNEL_ID_SERVER_ROOT_ALT2,
    ]

    if channel_obj.id in server_root_ids:
        return translator.gettext("under server")

    if is_caller_admin or not is_channel_hidden:
        channel_name = ttstr(channel_obj.name)
        # If the channel name is empty and it's the root channel, use a fallback name
        if not channel_name and channel_obj.id == WHO_CHANNEL_ID_ROOT:
            channel_name = translator.gettext("the root channel")

        return translator.gettext("in {channel_name}").format(channel_name=channel_name)

    return translator.gettext("under server")


def format_teamtalk_help_message(
    translator: NullTranslations,
    *,
    is_admin: bool,
) -> str:
    """Builds the help message for TeamTalk users."""
    _ = translator.gettext
    parts = [
        _("Available commands:"),
        _(
            "/sub - Get a link to subscribe to notifications.\n"
            "/unsub - Get a link to unsubscribe from notifications.\n"
            "/help - Show help."
        ),
    ]
    if is_admin:
        parts.extend(
            [
                _("\nAdmin commands (MAIN_ADMIN from config only):"),
                _(
                    "/add_admin <Telegram ID> [<Telegram ID>...] - Add bot admin.\n"
                    "/remove_admin <Telegram ID> [<Telegram ID>...] - "
                    "Remove bot admin."
                ),
            ]
        )
    return "\n".join(parts)
