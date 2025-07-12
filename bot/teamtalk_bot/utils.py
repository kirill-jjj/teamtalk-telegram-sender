"""Utility functions specific to TeamTalk bot operations."""

from __future__ import annotations

import asyncio
from collections.abc import (
    Awaitable,
    Callable,
)
import functools
import gettext
import html
import logging
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from aiogram.exceptions import TelegramAPIError
import pytalk
from pytalk.instance import TeamTalkInstance, sdk
from pytalk.message import Message as TeamTalkMessage
from pytalk.user import User as TeamTalkUser
from pytalk.user_account import UserAccount as TeamTalkUserAccount
from sqlalchemy.exc import SQLAlchemyError

from bot.config import Settings
from bot.constants import TT_HELP_MESSAGE_PART_DELAY, TT_MAX_MESSAGE_BYTES
from bot.telegram_bot.utils import send_telegram_message_individual

if TYPE_CHECKING:
    from bot.services_container import Services  # Forward reference for Services

logger = logging.getLogger(__name__)
ttstr = sdk.ttstr


# --- Functions moved from bot.core.utils ---


def get_effective_server_name(
    tt_instance: TeamTalkInstance | None,
    translator: gettext.GNUTranslations | gettext.NullTranslations,
    app_cfg: Settings,
) -> str:
    """Determines the effective server name to display.

    It prioritizes the server name from `app_cfg.SERVER_NAME`.
    If not set, it attempts to fetch it from the TeamTalk instance.
    Falls back to "Unknown Server" if unavailable.

    Args:
        tt_instance: The TeamTalk instance, or None.
        translator: The gettext translator object.
        app_cfg: The application configuration object.

    Returns:
        The server name string.
    """
    _ = translator.gettext
    server_name = app_cfg.teamtalk.server_name
    if not server_name:
        if tt_instance and tt_instance.connected:
            try:
                server_name = ttstr(tt_instance.server.get_properties().server_name)
                if not server_name:  # Check if empty string after ttstr
                    server_name = _("Unknown Server")
            except (TimeoutError, pytalk.exceptions.TeamTalkException):
                logger.exception(
                    "Error getting server name from TT instance %s.",
                    tt_instance.server_info.host if tt_instance.server_info else "N/A",
                )
                server_name = _("Unknown Server")
            except Exception:  # Catch any other unexpected error
                logger.exception(
                    "Unexpected error getting server name from TT instance %s.",
                    tt_instance.server_info.host if tt_instance.server_info else "N/A",
                )
                server_name = _("Unknown Server")
        else:
            server_name = _("Unknown Server")
    return server_name if server_name else _("Unknown Server")


def get_tt_user_display_name(user: TeamTalkUser, translator: gettext.GNUTranslations | gettext.NullTranslations) -> str:
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


def get_username_as_str(user_or_account: TeamTalkUser | TeamTalkUserAccount) -> str:
    """Extracts the username as a string from a TeamTalkUser or TeamTalkUserAccount object.

    Args:
        user_or_account: The TeamTalk user or account object.

    Returns:
        The username as a string, or an empty string if not found.
    """
    username = None
    if hasattr(user_or_account, "username"):
        username = user_or_account.username
    elif hasattr(user_or_account, "_account") and hasattr(user_or_account._account, "szUsername"):
        username = user_or_account._account.szUsername
    elif hasattr(user_or_account, "szUsername"):
        username = user_or_account.szUsername
    if isinstance(username, bytes):
        return str(ttstr(username))
    return str(username) if username is not None else ""


# --- End of moved functions ---


async def shutdown_tt_instance(instance: TeamTalkInstance) -> None:
    """Safely shuts down a single TeamTalk instance."""
    try:
        host_info = "Unknown Host"
        if hasattr(instance, "server_info") and instance.server_info and hasattr(instance.server_info, "host"):
            host_info = ttstr(instance.server_info.host)

        if instance.logged_in:
            logger.debug("Logging out from TT instance: %s", host_info)
            instance.logout()
        if instance.connected:
            logger.debug("Disconnecting from TT instance: %s", host_info)
            instance.disconnect()
        if hasattr(instance, "closeTeamTalk"):
            logger.debug("Closing TT instance: %s", host_info)
            instance.closeTeamTalk()
        logger.info("Successfully shut down TT instance for host: %s", host_info)
    except (pytalk.exceptions.TeamTalkException, TimeoutError, ConnectionError, OSError):
        host_info_err = "Unknown Host (during error)"
        if hasattr(instance, "server_info") and instance.server_info and hasattr(instance.server_info, "host"):
            host_info_err = ttstr(instance.server_info.host)
        logger.exception("Error during TT instance shutdown for %s.", host_info_err)


def _split_text_for_tt(text: str, max_len_bytes: int) -> list[str]:
    """Splits a long text message into parts suitable for TeamTalk.

    Args:
        text: The text to split.
        max_len_bytes: The maximum number of bytes per part.

    Returns:
        A list of text parts.
    """
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
                    parts_to_send_list.append(current_chunk_str[:last_safe_split_index_in_chunk])
                    remaining_text = remaining_text[last_safe_split_index_in_remaining:].lstrip()
                else:
                    parts_to_send_list.append(current_chunk_str)
                    remaining_text = remaining_text[i:].lstrip()
                break

            current_chunk_str += char_code
            current_chunk_bytes_len += char_bytes_len

            if char_code in ("\n", " "):
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


async def send_long_tt_reply(
    reply_method: Callable[[str], None], text: str, max_len_bytes: int = TT_MAX_MESSAGE_BYTES
) -> None:
    """Splits a long text message into parts suitable for TeamTalk and sends them."""
    if not text:
        return

    parts_to_send_list = await asyncio.to_thread(_split_text_for_tt, text, max_len_bytes)

    for part_idx, part_to_send_str in enumerate(parts_to_send_list):
        if part_to_send_str.strip():
            try:
                reply_method(part_to_send_str)
                encoded_len = len(part_to_send_str.encode("utf-8", errors="ignore"))
                logger.debug(
                    "Sent part %s/%s of TT message, length %s bytes.",
                    part_idx + 1,
                    len(parts_to_send_list),
                    encoded_len,
                )
                if part_idx < len(parts_to_send_list) - 1:
                    await asyncio.sleep(TT_HELP_MESSAGE_PART_DELAY)
            except pytalk.exceptions.TeamTalkException:
                logger.exception("Error sending part %s of TT message.", part_idx + 1)
                break


async def forward_tt_message_to_telegram_admin(
    message: TeamTalkMessage,
    services: Services,
    translator: gettext.GNUTranslations | gettext.NullTranslations,
) -> None:
    """Forwards a private TeamTalk message to the configured Telegram admin."""
    _ = translator.gettext
    if not services.config.telegram.admin_chat_id or not services.bot_message:
        logger.debug("Telegram admin chat ID or message bot not configured. Skipping TT forward.")
        return

    admin_chat_id = services.config.telegram.admin_chat_id
    server_name_to_display = get_effective_server_name(
        message.teamtalk_instance, translator, services.config
    )  # Now local
    sender_display = get_tt_user_display_name(message.user, translator)  # Now local
    message_content = message.content

    template_text_parts = _(
        "Message from server <b>{server_name}</b>\nFrom <b>{sender_name}</b>:\n\n{message_content}"
    ).format(
        server_name=html.escape(server_name_to_display),
        sender_name=html.escape(sender_display),
        message_content=html.escape(message_content),
    )

    was_sent: bool = await send_telegram_message_individual(
        bot_instance=services.bot_message,
        chat_id=admin_chat_id,
        services=services,
        text=template_text_parts,
    )

    if was_sent:
        message.reply(_("Message sent to Telegram successfully."))
    else:
        message.reply(_("Failed to send message: {error}").format(error=_("Failed to deliver message to Telegram")))


# --- Error Handling Decorator ---


P = ParamSpec("P")  # ParamSpec might not be used with ... but kept for potential future refinement
R = TypeVar("R")  # TypeVar for the return type of the original function (though simplified to Any below)


# Type for the original function that will be decorated.
# Using Awaitable[Any] as the decorator doesn't depend on the specific return type.
OriginalFunctionType = Callable[..., Awaitable[Any]]

# Type for the wrapped function returned by the decorator.
WrappedFunctionType = Callable[..., Awaitable[None]]

# Type for the decorator factory itself.
TTCommandHandlerDecorator = Callable[[OriginalFunctionType], WrappedFunctionType]


def handle_common_tt_command_errors(*, reply_to_user_on_error: bool = True) -> TTCommandHandlerDecorator:
    """Decorator to handle common exceptions (TelegramAPIError, SQLAlchemyError, TeamTalkException).

    for TeamTalk bot command handlers. Logs the error and optionally replies to the user.
    """

    def decorator(func: OriginalFunctionType) -> WrappedFunctionType:
        @functools.wraps(func)
        async def wrapper(
            tt_message: TeamTalkMessage, *args: ..., **kwargs: ...
        ) -> None:  # Use Any for args/kwargs for simplicity here
            try:
                await func(tt_message, *args, **kwargs)
            except (TelegramAPIError, SQLAlchemyError, pytalk.exceptions.TeamTalkException):
                # Try to get translator from kwargs for the error message
                translator = kwargs.get("translator")
                _ = (
                    translator.gettext
                    if isinstance(translator, gettext.GNUTranslations | gettext.NullTranslations)  # UP038
                    else lambda s: s
                )

                logger.exception(
                    "Error in TeamTalk command '%s' for user %s.",
                    func.__name__,
                    ttstr(tt_message.user.username) if tt_message and tt_message.user else "Unknown TT User",
                )
                if reply_to_user_on_error:
                    try:
                        # Ensure generic error message is translatable
                        error_msg_for_user = _("An error occurred. Please try again later.")
                        tt_message.reply(error_msg_for_user)
                    except Exception:  # Removed reply_exc as it's not used in log for TRY401
                        logger.exception(
                            "Failed to send error reply to TT user %s after command '%s' failed.",
                            ttstr(tt_message.user.username) if tt_message and tt_message.user else "Unknown TT User",
                            func.__name__,
                        )

        return wrapper

    return decorator
