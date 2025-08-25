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

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def get_effective_server_name(
    tt_instance: TeamTalkInstance | None,
    translator: gettext.NullTranslations,
    app_cfg: Settings,
) -> str:
    """Determines the effective server name to display.

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
