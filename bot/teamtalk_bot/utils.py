"""Utility functions specific to TeamTalk bot operations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import html
import logging
from typing import TYPE_CHECKING

import pytalk
from pytalk.instance import TeamTalkInstance, sdk
from pytalk.message import Message as TeamTalkMessage

from bot.constants import TT_HELP_MESSAGE_PART_DELAY, TT_MAX_MESSAGE_BYTES
from bot.core.utils import get_effective_server_name, get_tt_user_display_name
from bot.telegram_bot.utils import send_telegram_message_individual

if TYPE_CHECKING:
    from bot.services_container import Services  # Forward reference for Services

logger = logging.getLogger(__name__)
ttstr = sdk.ttstr


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
        # Check for closeTeamTalk attribute as it might not always be present
        # (though in typical TeamTalkInstance it should be)
        if hasattr(instance, "closeTeamTalk"):
            logger.debug("Closing TT instance: %s", host_info)
            instance.closeTeamTalk()
        logger.info("Successfully shut down TT instance for host: %s", host_info)
    except (pytalk.exceptions.TeamTalkException, TimeoutError, ConnectionError, OSError) as e:
        # Attempt to get host_info again in case it was not available before error
        host_info_err = "Unknown Host (during error)"
        if hasattr(instance, "server_info") and instance.server_info and hasattr(instance.server_info, "host"):
            host_info_err = ttstr(instance.server_info.host)
        logger.exception("Error during TT instance shutdown for %s: %s", host_info_err, e)


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
            # This else block for the for loop is reached if the loop completes
            # without a 'break', meaning the remaining_text was processed fully
            # within the loop's last iteration or was already empty.
            # The logic inside the loop should handle appending the last chunk.
            # If current_chunk_str has content and remaining_text is now empty,
            # it implies it was the last piece.
            if current_chunk_str and not remaining_text:  # Should have been appended already
                # This condition might indicate a slight redundancy in the loop's final append,
                # but it's safer to ensure the last piece isn't missed.
                # However, the primary logic for appending the final chunk is within the loop.
                pass  # logger.debug("_split_text_for_tt: Final chunk logic handled within loop.")
            remaining_text = ""  # Ensure it's cleared
    return parts_to_send_list


async def send_long_tt_reply(reply_method: Callable[[str], None], text: str, max_len_bytes: int = TT_MAX_MESSAGE_BYTES):
    """Splits a long text message into parts suitable for TeamTalk and sends them.

    Uses asyncio.to_thread for the potentially CPU-bound splitting logic.
    """
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
            except pytalk.exceptions.TeamTalkException as e:
                logger.error("Error sending part %s of TT message: %s", part_idx + 1, e)
                break


async def forward_tt_message_to_telegram_admin(
    message: TeamTalkMessage,
    services: Services,  # Changed from app: "Application"
    server_host_for_display: str,
):
    """Forwards a private TeamTalk message to the configured Telegram admin.

    Args:
        message: The TeamTalkMessage object.
        services: The application's services container.
        server_host_for_display: The display name of the TeamTalk server.
    """
    if not services.config.telegram.admin_chat_id or not services.bot_message:  # Use services.config, services.bot_message
        logger.debug("Telegram admin chat ID or message bot not configured. Skipping TT forward.")
        return

    admin_chat_id = services.config.telegram.admin_chat_id
    admin_settings = services.user_settings_cache.get(admin_chat_id)
    if admin_settings and admin_settings.language_code:
        admin_language_code = admin_settings.language_code
    else:
        admin_language_code = services.config.general.default_lang # Also update DEFAULT_LANG access here

    translator = services.get_translator(admin_language_code)
    _ = translator.gettext

    server_name_to_display = get_effective_server_name(message.teamtalk_instance, _, services.config)
    sender_display = get_tt_user_display_name(message.user, _)
    message_content = message.content

    template_text_parts = _(
        "Message from server <b>{server_name}</b>\nFrom <b>{sender_name}</b>:\n\n{message_content}"
    ).format(
        server_name=html.escape(server_name_to_display),
        sender_name=html.escape(sender_display),
        message_content=html.escape(message_content),
    )

    was_sent: bool = await send_telegram_message_individual(
        bot_instance=services.bot_message,  # Corrected: Use services.bot_message
        chat_id=admin_chat_id,
        language=admin_language_code,
        services=services,  # Corrected: Pass services
        text=template_text_parts,
        parse_mode="HTML",
    )

    if was_sent:
        message.reply(_("Message sent to Telegram successfully."))
    else:
        message.reply(_("Failed to send message: {error}").format(error=_("Failed to deliver message to Telegram")))
