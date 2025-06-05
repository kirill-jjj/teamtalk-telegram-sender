import logging
from aiogram import html # For quoting in messages if needed, though not directly used here
from aiogram.types import BotCommandScopeChat
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk
from pytalk.message import Message as TeamTalkMessage

from bot.config import app_config
from bot.localization import get_text
from bot.database.crud import create_deeplink, add_admin, remove_admin_db
from bot.telegram_bot.bot_instances import tg_bot_event # For get_me()
from bot.telegram_bot.commands import set_telegram_commands, ADMIN_COMMANDS, USER_COMMANDS
from bot.teamtalk_bot.utils import send_long_tt_reply # For help message
from bot.constants import (
    ACTION_SUBSCRIBE, ACTION_UNSUBSCRIBE, ACTION_SUBSCRIBE_AND_LINK_NOON,
)
# Define TT_UNKNOWN_COMMAND_TT in constants.py if it's different from the Telegram one
# For now, assuming it's the same or will be added to LOCALIZED_STRINGS
# If not, add: "tt_unknown_command_tt": {"en": "Unknown command. Available: /sub, /unsub, /add_admin, /remove_admin, /not on online, /help.", "ru": "Неизвестная команда. Доступны: /sub, /unsub, /add_admin, /remove_admin, /not on online, /help."}
# and use TT_UNKNOWN_COMMAND_TT key. For now, using the generic one.

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


async def handle_tt_subscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    bot_language: str # Language for bot's replies in TT
):
    try:
        sender_tt_username = ttstr(tt_message.user.username)
        # Deeplink does not require expected_telegram_id for general subscription
        token_val = await create_deeplink(
            session,
            action=ACTION_SUBSCRIBE_AND_LINK_NOON,
            payload=sender_tt_username
        )
        bot_info_val = await tg_bot_event.get_me() # Get bot's username for the link
        deeplink_url_val = f"https://t.me/{bot_info_val.username}?start={token_val}"

        reply_text_val = get_text("TT_SUBSCRIBE_DEEPLINK_TEXT", bot_language, deeplink_url=deeplink_url_val)
        tt_message.reply(reply_text_val)
        logger.info(f"Generated subscribe and link NOON deeplink {token_val} for TT user {sender_tt_username}")
    except Exception as e:
        logger.error(f"Error processing TT /sub command for {sender_tt_username}: {e}", exc_info=True)
        tt_message.reply(get_text("TT_SUBSCRIBE_ERROR", bot_language))


async def handle_tt_unsubscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    bot_language: str
):
    try:
        token_val = await create_deeplink(session, ACTION_UNSUBSCRIBE)
        bot_info_val = await tg_bot_event.get_me()
        deeplink_url_val = f"https://t.me/{bot_info_val.username}?start={token_val}"

        reply_text_val = get_text("TT_UNSUBSCRIBE_DEEPLINK_TEXT", bot_language, deeplink_url=deeplink_url_val)
        tt_message.reply(reply_text_val)
        logger.info(f"Generated unsubscribe deeplink {token_val} for TT user {ttstr(tt_message.user.username)}")
    except Exception as e:
        logger.error(f"Error processing TT /unsub command for {ttstr(tt_message.user.username)}: {e}", exc_info=True)
        tt_message.reply(get_text("TT_UNSUBSCRIBE_ERROR", bot_language))


async def handle_tt_add_admin_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    bot_language: str
):
    sender_username_val = ttstr(tt_message.user.username)
    # Check against ADMIN_USERNAME from config
    if not app_config.get("ADMIN_USERNAME") or sender_username_val != app_config["ADMIN_USERNAME"]:
        logger.warning(f"Unauthorized /add_admin attempt by TT user {sender_username_val}.")
        tt_message.reply(get_text("TT_ADMIN_CMD_NO_PERMISSION", bot_language))
        return

    try:
        parts_list = tt_message.content.split()
        if len(parts_list) < 2: # Command + at least one ID
            tt_message.reply(get_text("TT_ADD_ADMIN_PROMPT_IDS", bot_language))
            return

        telegram_ids_to_add_list = parts_list[1:]
        added_count_val = 0
        errors_list = []

        for telegram_id_str_val in telegram_ids_to_add_list:
            if telegram_id_str_val.isdigit():
                telegram_id_val = int(telegram_id_str_val)
                if await add_admin(session, telegram_id_val): # crud.add_admin
                    added_count_val += 1
                    logger.info(f"Admin TG ID {telegram_id_val} added by TT admin {sender_username_val}")
                    try:
                        await tg_bot_event.set_my_commands(commands=ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=telegram_id_val))
                        logger.info(f"Successfully set ADMIN_COMMANDS for newly added admin TG ID {telegram_id_val}")
                    except Exception as e_cmds:
                        logger.error(f"Failed to set ADMIN_COMMANDS for newly added admin TG ID {telegram_id_val}: {e_cmds}")
                else: # add_admin returned False (likely already exists or DB error)
                    errors_list.append(get_text("TT_ADD_ADMIN_ERROR_ALREADY_ADMIN", bot_language, telegram_id=telegram_id_val))
            else:
                errors_list.append(get_text("TT_ADD_ADMIN_ERROR_INVALID_ID", bot_language, telegram_id_str=telegram_id_str_val))

        reply_parts_list = []
        if added_count_val > 0:
            reply_parts_list.append(get_text("TT_ADD_ADMIN_SUCCESS", bot_language, count=added_count_val))
        if errors_list:
            reply_parts_list.append(get_text("TT_ADMIN_ERRORS_HEADER", bot_language) + "\n- ".join(errors_list))

        final_reply = "\n".join(reply_parts_list) if reply_parts_list else get_text("TT_ADMIN_NO_VALID_IDS", bot_language)
        tt_message.reply(final_reply)

    except Exception as e:
        logger.error(f"Error processing TT /add_admin command from {sender_username_val}: {e}", exc_info=True)
        tt_message.reply(get_text("TT_ADMIN_ERROR_PROCESSING", bot_language))


async def handle_tt_remove_admin_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    bot_language: str
):
    sender_username_val = ttstr(tt_message.user.username)
    if not app_config.get("ADMIN_USERNAME") or sender_username_val != app_config["ADMIN_USERNAME"]:
        logger.warning(f"Unauthorized /remove_admin attempt by TT user {sender_username_val}.")
        tt_message.reply(get_text("TT_ADMIN_CMD_NO_PERMISSION", bot_language))
        return

    try:
        parts_list = tt_message.content.split()
        if len(parts_list) < 2:
            tt_message.reply(get_text("TT_REMOVE_ADMIN_PROMPT_IDS", bot_language))
            return

        telegram_ids_to_remove_list = parts_list[1:]
        removed_count_val = 0
        errors_list = [] # Using info/errors header for consistency if some are not found

        for telegram_id_str_val in telegram_ids_to_remove_list:
            if telegram_id_str_val.isdigit():
                telegram_id_val = int(telegram_id_str_val)
                if await remove_admin_db(session, telegram_id_val): # crud.remove_admin_db
                    removed_count_val += 1
                    logger.info(f"Admin TG ID {telegram_id_val} removed by TT admin {sender_username_val}")
                    try:
                        await tg_bot_event.set_my_commands(commands=USER_COMMANDS, scope=BotCommandScopeChat(chat_id=telegram_id_val))
                        logger.info(f"Successfully set USER_COMMANDS for newly removed admin TG ID {telegram_id_val}")
                    except Exception as e_cmds:
                        logger.error(f"Failed to set USER_COMMANDS for newly removed admin TG ID {telegram_id_val}: {e_cmds}")
                else: # remove_admin_db returned False (not found or DB error)
                    errors_list.append(get_text("TT_REMOVE_ADMIN_ERROR_NOT_FOUND", bot_language, telegram_id=telegram_id_val))
            else:
                errors_list.append(get_text("TT_ADD_ADMIN_ERROR_INVALID_ID", bot_language, telegram_id_str=telegram_id_str_val)) # Re-use invalid ID message

        reply_parts_list = []
        if removed_count_val > 0:
            reply_parts_list.append(get_text("TT_REMOVE_ADMIN_SUCCESS", bot_language, count=removed_count_val))
        if errors_list:
            # Using TT_ADMIN_INFO_ERRORS_HEADER as it might contain "not found" which is info/error
            reply_parts_list.append(get_text("TT_ADMIN_INFO_ERRORS_HEADER", bot_language) + "\n- ".join(errors_list))

        final_reply = "\n".join(reply_parts_list) if reply_parts_list else get_text(TT_ADMIN_NO_VALID_IDS, bot_language) # Or a specific "no valid IDs to remove"
        tt_message.reply(final_reply)

    except Exception as e:
        logger.error(f"Error processing TT /remove_admin command from {sender_username_val}: {e}", exc_info=True)
        tt_message.reply(get_text("TT_ADMIN_ERROR_PROCESSING", bot_language))


async def handle_tt_help_command(
    tt_message: TeamTalkMessage,
    bot_language: str
):
    help_text_val = get_text("HELP_TEXT", bot_language) # Get the full help text object
    # The help_text_val is a dict with "en" and "ru" keys, or a string if already resolved.
    # Assuming get_text resolves it to a string based on bot_language.
    await send_long_tt_reply(tt_message.reply, help_text_val)


async def handle_tt_unknown_command(
    tt_message: TeamTalkMessage,
    bot_language: str
):
    # Use a specific "unknown command" message for TeamTalk if available
    reply_text_val = get_text("TT_UNKNOWN_COMMAND", bot_language) # Or TT_UNKNOWN_COMMAND_TT
    tt_message.reply(reply_text_val)
    logger.warning(f"Received unknown TT command from {ttstr(tt_message.user.username)}: {tt_message.content[:100]}")
