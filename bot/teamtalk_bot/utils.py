import logging
import asyncio
from typing import Callable
from aiogram.utils.formatting import Text, Bold

import pytalk
from pytalk import TeamTalkServerInfo
from pytalk.instance import TeamTalkInstance
from pytalk.message import Message as TeamTalkMessage
from bot.teamtalk_bot import bot_instance as tt_bot_module

from bot.config import app_config
from bot.language import get_translator
from bot.constants import (
    TT_HELP_MESSAGE_PART_DELAY,
    TT_MAX_MESSAGE_BYTES,
    DEFAULT_LANGUAGE
)
from bot.telegram_bot.utils import send_telegram_message_individual
from bot.telegram_bot.bot_instances import tg_bot_message
from bot.core.user_settings import USER_SETTINGS_CACHE
from bot.core.utils import get_effective_server_name, get_tt_user_display_name


logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr

RECONNECT_IN_PROGRESS = False

def initiate_reconnect_task(failed_instance: TeamTalkInstance | None):
    global RECONNECT_IN_PROGRESS
    if RECONNECT_IN_PROGRESS:
        logger.info("Reconnection process already running. New task not created.")
        return

    RECONNECT_IN_PROGRESS = True
    asyncio.create_task(_tt_reconnect(failed_instance))


def _split_text_for_tt(text: str, max_len_bytes: int) -> list[str]:
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

            if char_code == '\n':
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1
            elif char_code == ' ':
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1

            if i == len(remaining_text) - 1:
                parts_to_send_list.append(current_chunk_str)
                remaining_text = ""
                break
        else:
            if current_chunk_str and not remaining_text:
                 logger.debug("_split_text_for_tt: Appending final chunk in else block, this might be redundant.")
                 parts_to_send_list.append(current_chunk_str)
            remaining_text = ""
    return parts_to_send_list


async def send_long_tt_reply(reply_method: Callable[[str], None], text: str, max_len_bytes: int = TT_MAX_MESSAGE_BYTES):
    """
    Splits a long text message into parts suitable for TeamTalk and sends them.
    Uses asyncio.to_thread for the potentially CPU-bound splitting logic.
    """
    if not text:
        return

    parts_to_send_list = await asyncio.to_thread(_split_text_for_tt, text, max_len_bytes)

    for part_idx, part_to_send_str in enumerate(parts_to_send_list):
        if part_to_send_str.strip():
            try:
                reply_method(part_to_send_str)
                logger.debug(f"Sent part {part_idx + 1}/{len(parts_to_send_list)} of TT message, length {len(part_to_send_str.encode('utf-8', errors='ignore'))} bytes.")
                if part_idx < len(parts_to_send_list) - 1:
                    await asyncio.sleep(TT_HELP_MESSAGE_PART_DELAY)
            except pytalk.exceptions.TeamTalkException as e:
                logger.error(f"Error sending part {part_idx + 1} of TT message: {e}")
                break


async def forward_tt_message_to_telegram_admin(
    message: TeamTalkMessage
):
    if not app_config.TG_ADMIN_CHAT_ID or not tg_bot_message:
        logger.debug("Telegram admin chat ID or message bot not configured. Skipping TT forward.")
        return

    admin_chat_id = app_config.TG_ADMIN_CHAT_ID
    admin_settings = USER_SETTINGS_CACHE.get(admin_chat_id)
    admin_language = admin_settings.language if admin_settings else DEFAULT_LANGUAGE

    translator = get_translator(admin_language)
    _ = translator.gettext

    tt_instance = message.teamtalk_instance
    server_name = get_effective_server_name(tt_instance, _)
    sender_display = get_tt_user_display_name(message.user, _) # Assumes _ is the correct translator for user's name context
    message_content = message.content

    content = Text(
        _("Message from server "), Bold(server_name), "\n",
        _("From "), Bold(sender_display), ":\n\n",
        message_content
    )

    was_sent: bool = await send_telegram_message_individual(
        bot_instance=tg_bot_message,
        chat_id=admin_chat_id,
        language=admin_language,
        **content.as_kwargs()
    )

    if was_sent:
        message.reply(_("Message sent to Telegram successfully."))
    else:
        message.reply(_("Failed to send message: {error}").format(error=_("Failed to deliver message to Telegram")))


async def _tt_reconnect(failed_instance: TeamTalkInstance | None):
    global RECONNECT_IN_PROGRESS

    if failed_instance:
        try:
            server_host_info = "unknown server"
            if hasattr(failed_instance, 'server_info') and failed_instance.server_info and hasattr(failed_instance.server_info, 'host'):
                server_host_info = failed_instance.server_info.host
            logger.info(f"Closing old instance for server {server_host_info}...")

            if failed_instance.logged_in:
                logger.debug(f"Attempting logout for instance {server_host_info}")
                failed_instance.logout()
            if failed_instance.connected:
                logger.debug(f"Attempting disconnect for instance {server_host_info}")
                failed_instance.disconnect()

            logger.debug(f"Attempting closeTeamTalk for instance {server_host_info}")
            failed_instance.closeTeamTalk()

            if hasattr(tt_bot_module.tt_bot, 'teamtalks') and failed_instance in tt_bot_module.tt_bot.teamtalks:
                tt_bot_module.tt_bot.teamtalks.remove(failed_instance)
                logger.info(f"Old instance {server_host_info} removed from tt_bot.teamtalks list.")
            else:
                logger.info(f"Old instance {server_host_info} not found in tt_bot.teamtalks or list does not exist.")

            logger.info(f"Old instance {server_host_info} successfully closed and removed (attempt).")

        except (pytalk.exceptions.TeamTalkException, TimeoutError) as e:
            server_host_info_err = "unknown server"
            if hasattr(failed_instance, 'server_info') and failed_instance.server_info and hasattr(failed_instance.server_info, 'host'):
                server_host_info_err = failed_instance.server_info.host
            logger.error(f"Error closing old instance {server_host_info_err}: {e}", exc_info=True)

    tt_bot_module.current_tt_instance = None
    tt_bot_module.login_complete_time = None
    if failed_instance and hasattr(failed_instance, '_periodic_sync_task_running'):
        failed_instance._periodic_sync_task_running = False

    server_info_to_reconnect = None
    if failed_instance and hasattr(failed_instance, 'server_info') and failed_instance.server_info:
        server_info_to_reconnect = failed_instance.server_info
        logger.info(f"Using server_info from failed_instance: {server_info_to_reconnect.host}")
    elif app_config.HOSTNAME and app_config.PORT and app_config.USERNAME and app_config.PASSWORD:
        server_info_to_reconnect = TeamTalkServerInfo(
            host=app_config.HOSTNAME,
            tcp_port=app_config.PORT,
            udp_port=app_config.PORT,
            username=app_config.USERNAME,
            password=app_config.PASSWORD,
            encrypted=app_config.ENCRYPTED,
            nickname=app_config.NICKNAME
        )
        logger.info(f"Constructed server_info from app_config for reconnection: {server_info_to_reconnect.host}")
    else:
        logger.error("Cannot determine server information for reconnection. Reconnection stopped.")
        RECONNECT_IN_PROGRESS = False
        return

    while True:
        logger.info(f"Next reconnection attempt to {server_info_to_reconnect.host} in {app_config.TT_RECONNECT_RETRY_SECONDS} seconds...")
        await asyncio.sleep(app_config.TT_RECONNECT_RETRY_SECONDS)

        try:
            logger.info(f"Attempting to create new TeamTalk instance for {server_info_to_reconnect.host}...")
            await tt_bot_module.tt_bot.add_server(server_info_to_reconnect)

            await asyncio.sleep(app_config.TT_RECONNECT_CHECK_INTERVAL_SECONDS)

            if tt_bot_module.current_tt_instance and \
               tt_bot_module.current_tt_instance.connected and \
               tt_bot_module.current_tt_instance.logged_in and \
               hasattr(tt_bot_module.current_tt_instance.server_info, 'host') and \
               tt_bot_module.current_tt_instance.server_info.host == server_info_to_reconnect.host:
                logger.info(f"Reconnection to {server_info_to_reconnect.host} successful!")
                RECONNECT_IN_PROGRESS = False
                return
            else:
                logger.warning(f"Reconnection attempt to {server_info_to_reconnect.host} failed, instance not ready or not the correct one.")
                if tt_bot_module.tt_bot.teamtalks and \
                   hasattr(tt_bot_module.tt_bot.teamtalks[-1].server_info, 'host') and \
                   tt_bot_module.tt_bot.teamtalks[-1].server_info.host == server_info_to_reconnect.host and \
                   not (tt_bot_module.tt_bot.teamtalks[-1].connected and tt_bot_module.tt_bot.teamtalks[-1].logged_in):
                    logger.warning(f"Removing failed/partially created instance attempt for {server_info_to_reconnect.host} from tt_bot.teamtalks")
                    try:
                        last_instance = tt_bot_module.tt_bot.teamtalks.pop()
                        if last_instance.connected:
                            last_instance.disconnect()
                        last_instance.closeTeamTalk()
                    except Exception as e_cleanup: # This is a nested cleanup, general Exception is acceptable here
                        logger.error(f"Error cleaning up partially created instance: {e_cleanup}")

        except (pytalk.exceptions.PermissionError, ValueError, TimeoutError, pytalk.exceptions.TeamTalkException) as e:
            logger.error(f"Critical error during reconnection attempt to {server_info_to_reconnect.host}: {e}", exc_info=True)
            if tt_bot_module.tt_bot.teamtalks and \
               hasattr(tt_bot_module.tt_bot.teamtalks[-1].server_info, 'host') and \
               tt_bot_module.tt_bot.teamtalks[-1].server_info.host == server_info_to_reconnect.host:
                logger.warning(f"Removing instance for {server_info_to_reconnect.host} from tt_bot.teamtalks due to add_server() exception.")
                try:
                    last_instance = tt_bot_module.tt_bot.teamtalks.pop()
                    if last_instance.connected:
                        last_instance.disconnect()
                    last_instance.closeTeamTalk()
                except Exception as e_cleanup_exc: # Corrected indentation for this except
                    logger.error(f"Error cleaning up instance after add_server() exception: {e_cleanup_exc}")
