import logging
import functools # For functools.wraps
from typing import Optional, Callable, List
from aiogram.types import BotCommandScopeChat, BotCommand
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk
from pytalk.message import Message as TeamTalkMessage

from bot.config import app_config
from bot.localization import get_text
from bot.database.crud import create_deeplink, add_admin, remove_admin_db
from bot.telegram_bot.bot_instances import tg_bot_event # For get_me()
from bot.telegram_bot.commands import ADMIN_COMMANDS, USER_COMMANDS
from bot.teamtalk_bot.utils import send_long_tt_reply # For help message
from bot.constants import (
    ACTION_UNSUBSCRIBE, ACTION_SUBSCRIBE_AND_LINK_NOON,
)

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr # Convenience variable


# Decorator for TeamTalk admin commands
def is_tt_admin(func):
    @functools.wraps(func)
    async def wrapper(tt_message: TeamTalkMessage, *args, **kwargs):
        # Мы ожидаем, что bot_language будет в kwargs.
        bot_language = kwargs.get("bot_language")

        username = ttstr(tt_message.user.username)
        admin_username = app_config.get("ADMIN_USERNAME")

        if not admin_username or username != admin_username:
            logger.warning(
                f"Unauthorized admin command attempt by TT user {username} for function {func.__name__}."
            )
            # Если язык не передан, используем запасной вариант
            lang_for_reply = bot_language or app_config.get("DEFAULT_LANG", "en")
            tt_message.reply(get_text("TT_ADMIN_CMD_NO_PERMISSION", lang_for_reply))
            return None

        # Если проверка пройдена, вызываем оригинальную функцию
        return await func(tt_message, *args, **kwargs)
    return wrapper


async def _process_admin_ids(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    bot_language: str,
    parts_list: List[str],
    crud_function: Callable[[AsyncSession, int], bool],
    prompt_message_key: str,
    permission_success_message_key: str,
    permission_error_message_key: str,
    invalid_id_message_key: str,
    error_header_key: str,
    commands_to_set_on_success: List[BotCommand],
    log_action_description: str,
    tt_instance: pytalk.TeamTalkInstance # Changed type hint
):
    """
    Helper function to process adding or removing admin IDs.
    Handles parsing, CRUD operations, command setting, logging, and replies.
    """
    sender_username_val = ttstr(tt_message.user.username) # For logging in case of overall error
    try:
        if len(parts_list) < 2:  # Command + at least one ID
            tt_message.reply(get_text(prompt_message_key, bot_language))
            return

        telegram_ids_to_process = parts_list[1:]
        processed_count = 0
        errors_list = []

        for telegram_id_str_val in telegram_ids_to_process:
            if telegram_id_str_val.isdigit():
                telegram_id_val = int(telegram_id_str_val)
                if await crud_function(session, telegram_id_val):
                    processed_count += 1
                    logger.info(f"Admin TG ID {telegram_id_val} {log_action_description} by TT admin {sender_username_val}")
                    # If we are removing an admin, invalidate the cache
                    if crud_function.__name__ == 'remove_admin_db':
                        if tt_instance and hasattr(tt_instance, 'bot') and hasattr(tt_instance.bot, 'state_manager'):
                            tt_instance.bot.state_manager.admin_rights.pop(telegram_id_val, None)
                            logger.info(f"Admin rights cache invalidated for user {telegram_id_val}.")
                        else:
                            logger.warning(f"Could not invalidate admin_rights_cache for {telegram_id_val}: tt_instance or its state_manager not available.")
                    try:
                        await tg_bot_event.set_my_commands(
                            commands=commands_to_set_on_success,
                            scope=BotCommandScopeChat(chat_id=telegram_id_val)
                        )
                        logger.info(f"Successfully set commands for TG ID {telegram_id_val} after {log_action_description}")
                    except Exception as e_cmds:
                        logger.error(f"Failed to set commands for TG ID {telegram_id_val} after {log_action_description}: {e_cmds}")
                else:  # crud_function returned False (already admin / not found or DB error)
                    errors_list.append(get_text(permission_error_message_key, bot_language, telegram_id=telegram_id_val))
            else:
                errors_list.append(get_text(invalid_id_message_key, bot_language, telegram_id_str=telegram_id_str_val))

        reply_parts_list = []
        if processed_count > 0:
            reply_parts_list.append(get_text(permission_success_message_key, bot_language, count=processed_count))

        if errors_list:
            # Ensure there's a header only if there are errors.
            # The join adds a "- " prefix to each error message.
            error_messages_formatted = "- " + "\n- ".join(errors_list) # Add prefix to the first error too
            reply_parts_list.append(f"{get_text(error_header_key, bot_language)}\n{error_messages_formatted}")


        if not reply_parts_list: # No successes, no errors (e.g. empty ID list after command, though prompt should catch)
             # This case might be rare if the <2 check works, but as a fallback:
            if not telegram_ids_to_process: # Check if the list of IDs to process was empty
                 tt_message.reply(get_text(prompt_message_key, bot_language)) # Re-prompt if somehow no IDs were provided
                 return
            else: # All provided IDs were invalid but didn't trigger specific errors (unlikely with current logic)
                 tt_message.reply(get_text("TT_ADMIN_NO_VALID_IDS", bot_language))
                 return


        final_reply = "\n".join(reply_parts_list)
        tt_message.reply(final_reply)

    except Exception as e:
        logger.error(f"Error processing TT admin command for {log_action_description} by {sender_username_val}: {e}", exc_info=True)
        tt_message.reply(get_text("TT_ADMIN_ERROR_PROCESSING", bot_language))


async def _generate_and_reply_deeplink(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    bot_language: str,
    action: str,
    success_log_message: str,
    reply_text_key: str,
    error_reply_key: str,
    payload: Optional[str] = None,
):
    """
    Helper function to generate a deeplink, log success, and reply to the TeamTalk message.
    Includes error handling.
    """
    sender_tt_username = ttstr(tt_message.user.username) # Moved here for consistent logging
    try:
        token_val = await create_deeplink(
            session,
            action,
            payload=payload,
            expected_telegram_id=None
        )
        bot_info_val = await tg_bot_event.get_me()
        deeplink_url_val = f"https://t.me/{bot_info_val.username}?start={token_val}"

        logger.info(success_log_message.format(token=token_val, sender_username=sender_tt_username))
        reply_text_val = get_text(reply_text_key, bot_language, deeplink_url=deeplink_url_val)
        tt_message.reply(reply_text_val)
    except Exception as e:
        logger.error(
            f"Error processing deeplink action {action} for TT user {sender_tt_username}: {e}",
            exc_info=True
        )
        tt_message.reply(get_text(error_reply_key, bot_language))


async def handle_tt_subscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    bot_language: str # Language for bot's replies in TT
):
    sender_tt_username = ttstr(tt_message.user.username)
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        bot_language=bot_language,
        action=ACTION_SUBSCRIBE_AND_LINK_NOON,
        payload=sender_tt_username,
        success_log_message="Generated subscribe and link NOON deeplink {token} for TT user {sender_username}",
        reply_text_key="TT_SUBSCRIBE_DEEPLINK_TEXT",
        error_reply_key="TT_SUBSCRIBE_ERROR",
    )


async def handle_tt_unsubscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    bot_language: str
):
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        bot_language=bot_language,
        action=ACTION_UNSUBSCRIBE,
        payload=None, # No payload for unsubscribe
        success_log_message="Generated unsubscribe deeplink {token} for TT user {sender_username}",
        reply_text_key="TT_UNSUBSCRIBE_DEEPLINK_TEXT",
        error_reply_key="TT_UNSUBSCRIBE_ERROR",
    )


@is_tt_admin
async def handle_tt_add_admin_command(
    tt_message: TeamTalkMessage, *,
    session: AsyncSession,
    bot_language: str
):
    tt_instance = tt_message.server.teamtalk_instance # Added
    parts_list = tt_message.content.split()
    await _process_admin_ids(
        tt_message=tt_message,
        session=session,
        bot_language=bot_language,
        parts_list=parts_list,
        crud_function=add_admin,
        prompt_message_key="TT_ADD_ADMIN_PROMPT_IDS",
        permission_success_message_key="TT_ADD_ADMIN_SUCCESS",
        permission_error_message_key="TT_ADD_ADMIN_ERROR_ALREADY_ADMIN",
        invalid_id_message_key="TT_ADD_ADMIN_ERROR_INVALID_ID",
        error_header_key="TT_ADMIN_ERRORS_HEADER",
        commands_to_set_on_success=ADMIN_COMMANDS,
        log_action_description="added",
        tt_instance=tt_instance # Added
    )


@is_tt_admin
async def handle_tt_remove_admin_command(
    tt_message: TeamTalkMessage, *,
    session: AsyncSession,
    bot_language: str
):
    tt_instance = tt_message.server.teamtalk_instance # Added
    parts_list = tt_message.content.split()
    await _process_admin_ids(
        tt_message=tt_message,
        session=session,
        bot_language=bot_language,
        parts_list=parts_list,
        crud_function=remove_admin_db,
        prompt_message_key="TT_REMOVE_ADMIN_PROMPT_IDS",
        permission_success_message_key="TT_REMOVE_ADMIN_SUCCESS",
        permission_error_message_key="TT_REMOVE_ADMIN_ERROR_NOT_FOUND",
        invalid_id_message_key="TT_ADD_ADMIN_ERROR_INVALID_ID", # Reused
        error_header_key="TT_ADMIN_INFO_ERRORS_HEADER", # Specific for remove
        commands_to_set_on_success=USER_COMMANDS, # Set user commands on removal
        log_action_description="removed",
        tt_instance=tt_instance # Added
    )


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
    reply_text_val = get_text("TT_UNKNOWN_COMMAND", bot_language)
    tt_message.reply(reply_text_val)
    logger.warning(f"Received unknown TT command from {ttstr(tt_message.user.username)}: {tt_message.content[:100]}")
