import logging
import asyncio
from typing import Callable
from aiogram.utils.formatting import Text, Bold

import pytalk
from pytalk import TeamTalkServerInfo # Added for new _tt_reconnect
from pytalk.instance import TeamTalkInstance
from pytalk.message import Message as TeamTalkMessage
from pytalk.backoff import Backoff # Added for new _tt_reconnect
from bot.teamtalk_bot import bot_instance as tt_bot_module # Added for new _tt_reconnect
from pytalk.enums import UserStatusMode

from bot.config import app_config
from bot.language import get_translator
from bot.constants import (
    TT_HELP_MESSAGE_PART_DELAY,
    TT_MAX_MESSAGE_BYTES,
    RECONNECT_DELAY_SECONDS,
    RECONNECT_RETRY_SECONDS,
    RECONNECT_CHECK_INTERVAL_SECONDS,
    REJOIN_CHANNEL_DELAY_SECONDS,
    REJOIN_CHANNEL_RETRY_SECONDS,
    REJOIN_CHANNEL_MAX_ATTEMPTS,
    REJOIN_CHANNEL_FAIL_WAIT_SECONDS
)
# Import teamtalk_bot.bot_instance carefully to avoid circular dependencies if it needs utils
# For now, we pass tt_bot and current_tt_instance as arguments or access them via a getter if needed.
from bot.telegram_bot.utils import send_telegram_message_individual
from bot.telegram_bot.bot_instances import tg_bot_message
from bot.core.user_settings import USER_SETTINGS_CACHE
from bot.core.utils import get_effective_server_name, get_tt_user_display_name


logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr

RECONNECT_IN_PROGRESS = False # Added global flag

# New function as per subtask
def initiate_reconnect_task(failed_instance: TeamTalkInstance | None): # Allow None if called preemptively
    global RECONNECT_IN_PROGRESS
    if RECONNECT_IN_PROGRESS:
        logger.info("Процесс переподключения уже запущен. Новая задача не создается.")
        return

    RECONNECT_IN_PROGRESS = True
    # Ensure this task is created correctly.
    # The failed_instance might be None if called from a place where the instance is already gone.
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
        last_safe_split_index_in_chunk = -1 # Index within the current_chunk_str being built
        last_safe_split_index_in_remaining = -1 # Corresponding index in remaining_text

        # Iterate through characters of remaining_text to build a chunk
        for i, char_code in enumerate(remaining_text):
            char_bytes = char_code.encode("utf-8", errors="ignore")
            char_bytes_len = len(char_bytes)

            if current_chunk_bytes_len + char_bytes_len > max_len_bytes:
                # Current char would make chunk too long
                if last_safe_split_index_in_chunk != -1:
                    # We have a preferred split point (newline or space)
                    parts_to_send_list.append(current_chunk_str[:last_safe_split_index_in_chunk])
                    remaining_text = remaining_text[last_safe_split_index_in_remaining:].lstrip()
                else:
                    # No preferred split point, must split at current_chunk_str (hard split)
                    parts_to_send_list.append(current_chunk_str)
                    remaining_text = remaining_text[i:].lstrip()
                break # Break from inner loop to process next chunk

            current_chunk_str += char_code
            current_chunk_bytes_len += char_bytes_len

            if char_code == '\n': # Preferred split
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1
            elif char_code == ' ': # Secondary preferred split
                # Only update if newline hasn't been found or if it's closer
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1

            if i == len(remaining_text) - 1: # Reached end of remaining_text
                parts_to_send_list.append(current_chunk_str)
                remaining_text = "" # Mark as fully processed
                break # Break from inner loop
        else: # Inner loop didn't break, means remaining_text was consumed or became empty
            if current_chunk_str and not remaining_text: # Should have been caught by outer if
                 logger.debug("_split_text_for_tt: Appending final chunk in else block, this might be redundant.")
                 parts_to_send_list.append(current_chunk_str)
            remaining_text = "" # Ensure termination
    return parts_to_send_list


async def send_long_tt_reply(reply_method: Callable[[str], None], text: str, max_len_bytes: int = TT_MAX_MESSAGE_BYTES):
    """
    Splits a long text message into parts suitable for TeamTalk and sends them.
    Ensures that splitting doesn't break in the middle of a multi-byte character.
    Prioritizes splitting at newlines, then spaces.
    Uses asyncio.to_thread for the splitting logic.
    """
    if not text:
        return

    parts_to_send_list = await asyncio.to_thread(_split_text_for_tt, text, max_len_bytes)

    for part_idx, part_to_send_str in enumerate(parts_to_send_list):
        if part_to_send_str.strip(): # Don't send empty parts
            try:
                reply_method(part_to_send_str)
                logger.debug(f"Sent part {part_idx + 1}/{len(parts_to_send_list)} of TT message, length {len(part_to_send_str.encode('utf-8', errors='ignore'))} bytes.")
                if part_idx < len(parts_to_send_list) - 1:
                    await asyncio.sleep(TT_HELP_MESSAGE_PART_DELAY)
            except Exception as e:
                logger.error(f"Error sending part {part_idx + 1} of TT message: {e}")
                # Decide if you want to stop or continue sending other parts
                break


async def forward_tt_message_to_telegram_admin(
    message: TeamTalkMessage
):
    if not app_config.TG_ADMIN_CHAT_ID or not tg_bot_message:
        logger.debug("Telegram admin chat ID or message bot not configured. Skipping TT forward.")
        return

    admin_chat_id = app_config.TG_ADMIN_CHAT_ID
    admin_settings = USER_SETTINGS_CACHE.get(admin_chat_id) # type: ignore
    admin_language = admin_settings.language if admin_settings else DEFAULT_LANGUAGE

    translator = get_translator(admin_language)
    _ = translator.gettext

    tt_instance = message.teamtalk_instance

    server_name = get_effective_server_name(tt_instance, _)
    # get_tt_user_display_name now expects `_` (translator func) as its second argument
    sender_display = get_tt_user_display_name(message.user, _)
    message_content = message.content

    # text_to_send = _("Message from server {server_name}\nFrom {sender_display}:\n\n{message_text}").format(
    #     server_name=html.quote(server_name),
    #     sender_display=html.quote(sender_display),
    #     message_text=html.quote(message_content)
    # )
    content = Text(
        _("Message from server "), Bold(server_name), "\n",
        _("From "), Bold(sender_display), ":\n\n",
        message_content  # No html.quote needed here, Text handles escaping for supported entities.
    )

    # Use the individual message sending utility
    was_sent: bool = await send_telegram_message_individual(
        bot_instance=tg_bot_message, # Use the dedicated message bot
        chat_id=admin_chat_id,
        # text=text_to_send, # Removed
        language=admin_language,
        **content.as_kwargs()
    )

    if was_sent:
        message.reply(_("Message sent to Telegram successfully."))
    else:
        message.reply(_("Failed to send message: {error}").format(error=_("Failed to deliver message to Telegram")))


async def _tt_reconnect(failed_instance: TeamTalkInstance | None):
    global RECONNECT_IN_PROGRESS

    # 1. Correctly terminate the old instance
    if failed_instance:
        try:
            server_host_info = "unknown server"
            if hasattr(failed_instance, 'server_info') and failed_instance.server_info and hasattr(failed_instance.server_info, 'host'):
                server_host_info = failed_instance.server_info.host
            logger.info(f"Закрытие старого инстанса для сервера {server_host_info}...")

            if failed_instance.logged_in:
                logger.debug(f"Attempting logout for instance {failed_instance.server_info.host}")
                failed_instance.logout()
            if failed_instance.connected:
                logger.debug(f"Attempting disconnect for instance {failed_instance.server_info.host}")
                failed_instance.disconnect()

            logger.debug(f"Attempting closeTeamTalk for instance {failed_instance.server_info.host}")
            failed_instance.closeTeamTalk() # This should release SDK resources

            # Critical: Remove from pytalk's list of instances if present
            if hasattr(tt_bot_module.tt_bot, 'teamtalks') and failed_instance in tt_bot_module.tt_bot.teamtalks:
                tt_bot_module.tt_bot.teamtalks.remove(failed_instance)
                logger.info(f"Старый инстанс {server_host_info} удален из списка tt_bot.teamtalks.")
            else:
                logger.info(f"Старый инстанс {server_host_info} не найден в tt_bot.teamtalks или список отсутствует.")

            logger.info(f"Старый инстанс {server_host_info} успешно закрыт и удален (попытка).")

        except Exception as e:
            server_host_info_err = "unknown server"
            if hasattr(failed_instance, 'server_info') and failed_instance.server_info and hasattr(failed_instance.server_info, 'host'):
                server_host_info_err = failed_instance.server_info.host
            logger.error(f"Ошибка при закрытии старого инстанса {server_host_info_err}: {e}", exc_info=True)

    # Reset global state tracking current instance
    tt_bot_module.current_tt_instance = None
    tt_bot_module.login_complete_time = None
    # Also reset the periodic sync task flag if it exists on the instance, though failed_instance is now "gone"
    if failed_instance and hasattr(failed_instance, '_periodic_sync_task_running'):
        failed_instance._periodic_sync_task_running = False


    # Determine server_info for reconnection
    server_info_to_reconnect = None
    if failed_instance and hasattr(failed_instance, 'server_info') and failed_instance.server_info:
        server_info_to_reconnect = failed_instance.server_info
        logger.info(f"Using server_info from failed_instance: {server_info_to_reconnect.host}")
    elif app_config.HOSTNAME and app_config.PORT and app_config.USERNAME and app_config.PASSWORD:
        server_info_to_reconnect = TeamTalkServerInfo(
            host=app_config.HOSTNAME,
            tcp_port=app_config.PORT,
            udp_port=app_config.PORT, # Assuming UDP same as TCP
            username=app_config.USERNAME,
            password=app_config.PASSWORD,
            encrypted=app_config.ENCRYPTED,
            nickname=app_config.NICKNAME
        )
        logger.info(f"Constructed server_info from app_config for reconnection: {server_info_to_reconnect.host}")
    else:
        logger.error("Невозможно определить информацию о сервере для переподключения. Переподключение остановлено.")
        RECONNECT_IN_PROGRESS = False
        return

    backoff = Backoff(base=5, max_value=60) # Start with 5s, max 60s

    while True:
        delay = backoff.delay()
        logger.info(f"Следующая попытка переподключения к {server_info_to_reconnect.host} через {delay:.2f} секунд...")
        await asyncio.sleep(delay)

        try:
            logger.info(f"Попытка создания нового инстанса TeamTalk для {server_info_to_reconnect.host}...")
            await tt_bot_module.tt_bot.add_server(server_info_to_reconnect)

            await asyncio.sleep(RECONNECT_CHECK_INTERVAL_SECONDS)

            if tt_bot_module.current_tt_instance and \
               tt_bot_module.current_tt_instance.connected and \
               tt_bot_module.current_tt_instance.logged_in and \
               hasattr(tt_bot_module.current_tt_instance.server_info, 'host') and \
               tt_bot_module.current_tt_instance.server_info.host == server_info_to_reconnect.host:
                logger.info(f"Переподключение к {server_info_to_reconnect.host} успешно завершено!")
                RECONNECT_IN_PROGRESS = False
                return
            else:
                logger.warning(f"Попытка переподключения к {server_info_to_reconnect.host} не удалась, инстанс не готов или не тот.")
                if tt_bot_module.tt_bot.teamtalks and \
                   hasattr(tt_bot_module.tt_bot.teamtalks[-1].server_info, 'host') and \
                   tt_bot_module.tt_bot.teamtalks[-1].server_info.host == server_info_to_reconnect.host and \
                   not (tt_bot_module.tt_bot.teamtalks[-1].connected and tt_bot_module.tt_bot.teamtalks[-1].logged_in):
                    logger.warning(f"Removing failed/partially created instance attempt for {server_info_to_reconnect.host} from tt_bot.teamtalks")
                    try:
                        last_instance = tt_bot_module.tt_bot.teamtalks.pop()
                        if last_instance.connected: last_instance.disconnect()
                        last_instance.closeTeamTalk()
                    except Exception as e_cleanup:
                        logger.error(f"Error cleaning up partially created instance: {e_cleanup}")

        except Exception as e:
            logger.error(f"Критическая ошибка во время попытки переподключения к {server_info_to_reconnect.host}: {e}", exc_info=True)
            if tt_bot_module.tt_bot.teamtalks and \
               hasattr(tt_bot_module.tt_bot.teamtalks[-1].server_info, 'host') and \
               tt_bot_module.tt_bot.teamtalks[-1].server_info.host == server_info_to_reconnect.host:
                 logger.warning(f"Removing instance for {server_info_to_reconnect.host} from tt_bot.teamtalks due to add_server() exception.")
                 try:
                    last_instance = tt_bot_module.tt_bot.teamtalks.pop()
                    if last_instance.connected: last_instance.disconnect()
                    last_instance.closeTeamTalk()
                 except Exception as e_cleanup_exc:
                     logger.error(f"Error cleaning up instance after add_server() exception: {e_cleanup_exc}")

# Old _tt_rejoin_channel function removed as its calls were replaced by the new full reconnect logic.
# async def _tt_rejoin_channel(tt_instance: TeamTalkInstance):
#     """Handles the TeamTalk channel rejoin logic."""
#     from bot.teamtalk_bot import bot_instance as tt_bot_module
#
#     if tt_instance is not tt_bot_module.current_tt_instance:
#         logger.warning("Rejoin channel called for an outdated/inactive TT instance. Aborting.")
#         return
#
#     logger.info("Starting TeamTalk channel rejoin process...")
#     await asyncio.sleep(REJOIN_CHANNEL_DELAY_SECONDS)
#     attempts = 0
#
#     while True:
#         if not tt_bot_module.current_tt_instance or \
#            not tt_bot_module.current_tt_instance.connected or \
#            not tt_bot_module.current_tt_instance.logged_in:
#             logger.warning("TT not connected/logged in during rejoin attempt. Aborting rejoin and triggering reconnect.")
#             if not tt_bot_module.current_tt_instance: # If instance is gone, ensure reconnect is scheduled
#                 tt_bot_module.login_complete_time = None
#                 # asyncio.create_task(_tt_reconnect()) # This would call the new _tt_reconnect
#                 # Replaced by initiate_reconnect_task if needed from event handlers
#             return
#
#         attempts += 1
#         try:
#             channel_id_or_path = app_config.CHANNEL
#             channel_id = -1
#             channel_name = ""
#
#             if channel_id_or_path.isdigit():
#                 channel_id = int(channel_id_or_path)
#                 channel_obj = tt_instance.get_channel(channel_id)
#                 channel_name = ttstr(channel_obj.name) if channel_obj else f"ID {channel_id}"
#             else: # Assume it's a path
#                 channel_obj = tt_instance.get_channel_from_path(channel_id_or_path)
#                 if channel_obj:
#                     channel_id = channel_obj.id
#                     channel_name = ttstr(channel_obj.name)
#                 else:
#                     logger.error(f"Channel path '{channel_id_or_path}' not found during rejoin (Attempt {attempts}).")
#                     await asyncio.sleep(REJOIN_CHANNEL_RETRY_SECONDS)
#                     continue # Retry resolving path
#
#             if channel_id == -1:
#                 logger.error(f"Could not resolve channel '{channel_id_or_path}' to an ID during rejoin (Attempt {attempts}).")
#                 await asyncio.sleep(REJOIN_CHANNEL_RETRY_SECONDS)
#                 continue
#
#             logger.info(f"Attempting to rejoin channel: {channel_name} (ID: {channel_id}) (Attempt {attempts})")
#             tt_instance.join_channel_by_id(channel_id, password=app_config.CHANNEL_PASSWORD)
#             await asyncio.sleep(1) # Give time for action to complete
#
#             current_channel_id = tt_instance.getMyChannelID()
#             if current_channel_id == channel_id:
#                 logger.info(f"Successfully rejoined channel {channel_name}.")
#                 # Update status text again in case it was lost
#                 tt_instance.change_status(UserStatusMode.ONLINE, app_config.STATUS_TEXT)
#                 break # Exit rejoin loop
#             else:
#                 logger.warning(f"Failed to rejoin channel {channel_name}. Current channel ID: {current_channel_id}. Retrying...")
#
#         except Exception as e:
#             logger.error(f"Error during channel rejoin loop (Attempt {attempts}): {e}. Retrying...")
#
#         if attempts >= REJOIN_CHANNEL_MAX_ATTEMPTS:
#             logger.warning(f"Failed to rejoin channel after {REJOIN_CHANNEL_MAX_ATTEMPTS} attempts. Waiting {REJOIN_CHANNEL_FAIL_WAIT_SECONDS}s before trying again from scratch.")
#             await asyncio.sleep(REJOIN_CHANNEL_FAIL_WAIT_SECONDS)
#             attempts = 0 # Reset attempts for a fresh set
#         else:
#             await asyncio.sleep(REJOIN_CHANNEL_RETRY_SECONDS)
