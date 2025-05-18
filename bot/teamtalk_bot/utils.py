import logging
import asyncio
from typing import Callable
from aiogram import html

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.channel import Channel as PytalkChannel
from pytalk.enums import UserStatusMode

from bot.config import app_config
from bot.localization import get_text
from bot.constants import (
    WHO_USER_UNKNOWN,
    TT_FORWARD_MESSAGE_TEXT,
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
from bot.teamtalk_bot.bot_instance import tt_bot, current_tt_instance, login_complete_time
from bot.telegram_bot.utils import send_telegram_message_individual # For forwarding
from bot.telegram_bot.bot_instances import tg_bot_message # For forwarding
from bot.core.user_settings import USER_SETTINGS_CACHE # For admin language
from bot.constants import DEFAULT_LANGUAGE


logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


async def send_long_tt_reply(reply_method: Callable[[str], None], text: str, max_len_bytes: int = TT_MAX_MESSAGE_BYTES):
    """
    Splits a long text message into parts suitable for TeamTalk and sends them.
    Ensures that splitting doesn't break in the middle of a multi-byte character.
    Prioritizes splitting at newlines, then spaces.
    """
    if not text:
        return

    parts_to_send_list = []
    remaining_text_val = text

    while remaining_text_val:
        if len(remaining_text_val.encode("utf-8", errors="ignore")) <= max_len_bytes:
            parts_to_send_list.append(remaining_text_val)
            break # Last part

        current_chunk_str = ""
        current_chunk_bytes_len = 0
        last_safe_split_index_in_chunk = -1 # Index within the current_chunk_str being built
        last_safe_split_index_in_remaining = -1 # Corresponding index in remaining_text_val

        # Iterate through characters of remaining_text_val to build a chunk
        for i, char_code_val in enumerate(remaining_text_val):
            char_bytes = char_code_val.encode("utf-8", errors="ignore")
            char_bytes_len = len(char_bytes)

            if current_chunk_bytes_len + char_bytes_len > max_len_bytes:
                # Current char would make chunk too long
                if last_safe_split_index_in_chunk != -1:
                    # We have a preferred split point (newline or space)
                    parts_to_send_list.append(current_chunk_str[:last_safe_split_index_in_chunk])
                    remaining_text_val = remaining_text_val[last_safe_split_index_in_remaining:].lstrip()
                else:
                    # No preferred split point, must split at current_chunk_str (hard split)
                    parts_to_send_list.append(current_chunk_str)
                    remaining_text_val = remaining_text_val[i:].lstrip()
                break # Break from inner loop to process next chunk

            current_chunk_str += char_code_val
            current_chunk_bytes_len += char_bytes_len

            if char_code_val == '\n': # Preferred split
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1
            elif char_code_val == ' ': # Secondary preferred split
                # Only update if newline hasn't been found or if it's closer
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1

            if i == len(remaining_text_val) - 1: # Reached end of remaining_text_val
                parts_to_send_list.append(current_chunk_str)
                remaining_text_val = "" # Mark as fully processed
                break # Break from inner loop
        else: # Inner loop didn't break, means remaining_text_val was consumed or became empty
            if current_chunk_str and not remaining_text_val: # Should have been caught by outer if
                 parts_to_send_list.append(current_chunk_str) # Add any final part
            remaining_text_val = "" # Ensure termination

    for part_idx_val, part_to_send_str_val in enumerate(parts_to_send_list):
        if part_to_send_str_val.strip(): # Don't send empty parts
            try:
                reply_method(part_to_send_str_val)
                logger.debug(f"Sent part {part_idx_val + 1}/{len(parts_to_send_list)} of TT message, length {len(part_to_send_str_val.encode('utf-8', errors='ignore'))} bytes.")
                if part_idx_val < len(parts_to_send_list) - 1:
                    await asyncio.sleep(TT_HELP_MESSAGE_PART_DELAY)
            except Exception as e:
                logger.error(f"Error sending part {part_idx_val + 1} of TT message: {e}")
                # Decide if you want to stop or continue sending other parts
                break


async def forward_tt_message_to_telegram_admin(
    message: TeamTalkMessage, # The TT message object
    tt_instance_for_check: TeamTalkInstance | None = None # For silent notification check
):
    if not app_config.get("TG_ADMIN_CHAT_ID") or not tg_bot_message:
        logger.debug("Telegram admin chat ID or message bot not configured. Skipping TT forward.")
        return

    admin_chat_id = app_config["TG_ADMIN_CHAT_ID"]
    admin_settings = USER_SETTINGS_CACHE.get(admin_chat_id)
    admin_language = admin_settings.language if admin_settings else DEFAULT_LANGUAGE

    tt_instance_val = message.teamtalk_instance # Instance from which message originated
    server_name_val = app_config.get("SERVER_NAME") # Use configured name first
    if not server_name_val:
        if tt_instance_val and tt_instance_val.connected:
            try:
                server_name_val = ttstr(tt_instance_val.server.get_properties().server_name)
            except Exception as e:
                logger.error(f"Could not get server name from TT instance for forwarding: {e}")
                server_name_val = "Unknown Server"
        else:
            server_name_val = "Unknown Server"

    sender_nickname = ttstr(message.user.nickname)
    sender_username = ttstr(message.user.username)
    message_content = message.content

    sender_display_val = sender_nickname or sender_username or get_text(WHO_USER_UNKNOWN, admin_language)

    text_to_send = get_text(
        TT_FORWARD_MESSAGE_TEXT,
        admin_language,
        server_name=html.quote(server_name_val),
        sender_display=html.quote(sender_display_val),
        message_text=html.quote(message_content)
    )

    # Use the individual message sending utility
    asyncio.create_task(send_telegram_message_individual(
        bot_instance=tg_bot_message, # Use the dedicated message bot
        chat_id=admin_chat_id,
        text=text_to_send,
        language=admin_language,
        reply_tt_method=message.reply, # Pass the reply method for feedback
        tt_instance_for_check=tt_instance_for_check # For silent check
    ))


async def _tt_reconnect():
    """Handles the TeamTalk reconnection logic."""
    # Use global tt_bot, current_tt_instance, login_complete_time from teamtalk_bot.bot_instance
    from bot.teamtalk_bot import bot_instance as tt_bot_module
    from bot.teamtalk_bot.events import on_ready as tt_on_ready # Import on_ready

    if tt_bot_module.current_tt_instance: # Check if already connected or reconnecting
        logger.info("Reconnect already in progress or instance exists, skipping new task.")
        return

    logger.info("Starting TeamTalk reconnection process...")
    tt_bot_module.current_tt_instance = None
    tt_bot_module.login_complete_time = None
    await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    while True:
        try:
            logger.info("Attempting to re-add server via on_ready logic...")
            # on_ready is expected to set current_tt_instance and login_complete_time on success
            await tt_on_ready() # Call the on_ready event handler
            await asyncio.sleep(RECONNECT_CHECK_INTERVAL_SECONDS) # Wait for connection to establish

            if tt_bot_module.current_tt_instance and \
               tt_bot_module.current_tt_instance.connected and \
               tt_bot_module.current_tt_instance.logged_in:
                logger.info("TeamTalk reconnected successfully.")
                break # Exit reconnect loop
            else:
                logger.warning("TeamTalk reconnection attempt failed (instance not ready/connected/logged in). Retrying...")
                tt_bot_module.current_tt_instance = None # Ensure it's reset for next attempt
                tt_bot_module.login_complete_time = None
        except Exception as e:
            logger.error(f"Error during TeamTalk reconnection attempt: {e}. Retrying...")
            tt_bot_module.current_tt_instance = None
            tt_bot_module.login_complete_time = None
        await asyncio.sleep(RECONNECT_RETRY_SECONDS)


async def _tt_rejoin_channel(tt_instance: TeamTalkInstance):
    """Handles the TeamTalk channel rejoin logic."""
    from bot.teamtalk_bot import bot_instance as tt_bot_module

    if tt_instance is not tt_bot_module.current_tt_instance:
        logger.warning("Rejoin channel called for an outdated/inactive TT instance. Aborting.")
        return

    logger.info("Starting TeamTalk channel rejoin process...")
    await asyncio.sleep(REJOIN_CHANNEL_DELAY_SECONDS)
    attempts_val = 0

    while True:
        if not tt_bot_module.current_tt_instance or \
           not tt_bot_module.current_tt_instance.connected or \
           not tt_bot_module.current_tt_instance.logged_in:
            logger.warning("TT not connected/logged in during rejoin attempt. Aborting rejoin and triggering reconnect.")
            if not tt_bot_module.current_tt_instance: # If instance is gone, ensure reconnect is scheduled
                tt_bot_module.login_complete_time = None
                asyncio.create_task(_tt_reconnect())
            return

        attempts_val += 1
        try:
            channel_id_or_path_val = app_config["CHANNEL"]
            channel_id_val = -1
            channel_name_val = "" # For logging

            if channel_id_or_path_val.isdigit():
                channel_id_val = int(channel_id_or_path_val)
                channel_obj_val = tt_instance.get_channel(channel_id_val) # PyTalk method
                channel_name_val = ttstr(channel_obj_val.name) if channel_obj_val else f"ID {channel_id_val}"
            else: # Assume it's a path
                channel_obj_val = tt_instance.get_channel_from_path(channel_id_or_path_val) # PyTalk method
                if channel_obj_val:
                    channel_id_val = channel_obj_val.id
                    channel_name_val = ttstr(channel_obj_val.name)
                else:
                    logger.error(f"Channel path '{channel_id_or_path_val}' not found during rejoin (Attempt {attempts_val}).")
                    await asyncio.sleep(REJOIN_CHANNEL_RETRY_SECONDS)
                    continue # Retry resolving path

            if channel_id_val == -1:
                logger.error(f"Could not resolve channel '{channel_id_or_path_val}' to an ID during rejoin (Attempt {attempts_val}).")
                await asyncio.sleep(REJOIN_CHANNEL_RETRY_SECONDS)
                continue

            logger.info(f"Attempting to rejoin channel: {channel_name_val} (ID: {channel_id_val}) (Attempt {attempts_val})")
            tt_instance.join_channel_by_id(channel_id_val, password=app_config.get("CHANNEL_PASSWORD"))
            await asyncio.sleep(1) # Give time for action to complete

            current_channel_id_val = tt_instance.getMyChannelID()
            if current_channel_id_val == channel_id_val:
                logger.info(f"Successfully rejoined channel {channel_name_val}.")
                # Update status text again in case it was lost
                tt_instance.change_status(UserStatusMode.ONLINE, app_config["STATUS_TEXT"])
                break # Exit rejoin loop
            else:
                logger.warning(f"Failed to rejoin channel {channel_name_val}. Current channel ID: {current_channel_id_val}. Retrying...")

        except Exception as e:
            logger.error(f"Error during channel rejoin loop (Attempt {attempts_val}): {e}. Retrying...")

        if attempts_val >= REJOIN_CHANNEL_MAX_ATTEMPTS:
            logger.warning(f"Failed to rejoin channel after {REJOIN_CHANNEL_MAX_ATTEMPTS} attempts. Waiting {REJOIN_CHANNEL_FAIL_WAIT_SECONDS}s before trying again from scratch.")
            await asyncio.sleep(REJOIN_CHANNEL_FAIL_WAIT_SECONDS)
            attempts_val = 0 # Reset attempts for a fresh set
        else:
            await asyncio.sleep(REJOIN_CHANNEL_RETRY_SECONDS)
