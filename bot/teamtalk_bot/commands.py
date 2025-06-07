import logging
import functools # For functools.wraps
from typing import Optional, Callable, List
from bot.state import ADMIN_RIGHTS_CACHE
from aiogram.filters import CommandObject
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


def _parse_telegram_ids(command_args: str | None) -> tuple[list[int], list[str]]:
    """Parses a string of arguments into a list of valid Telegram IDs and a list of invalid entries."""
    if not command_args:
        return [], []

    valid_ids = []
    invalid_entries = []
    parts = command_args.split()

    for part in parts:
        if part.isdigit():
            valid_ids.append(int(part))
        else:
            invalid_entries.append(part)
    return valid_ids, invalid_entries


async def _execute_admin_action_for_id(
    session: AsyncSession,
    telegram_id: int,
    crud_function: Callable[[AsyncSession, int], bool], # Assuming crud_function returns bool
    commands_to_set: list[BotCommand]
) -> bool:
    """Executes a CRUD function for a single ID and sets Telegram commands on success."""
    # crud_function is async as per typical DB ops with AsyncSession
    if await crud_function(session, telegram_id):
        # The __name__ check is kept as per prompt, requires remove_admin_db to be in scope
        if crud_function.__name__ == 'remove_admin_db':
            ADMIN_RIGHTS_CACHE.pop(telegram_id, None)
            logger.info(f"Admin rights cache invalidated for user {telegram_id}.")

        try:
            await tg_bot_event.set_my_commands(
                commands=commands_to_set,
                scope=BotCommandScopeChat(chat_id=telegram_id)
            )
        except Exception as e:
            logger.error(f"Failed to set commands for TG ID {telegram_id} after {crud_function.__name__}: {e}")
        return True
    return False


def _create_admin_action_report(
    language: str,
    success_count: int,
    failed_ids: list[int],
    invalid_entries: list[str],
    success_msg_key: str,
    error_msg_key: str,
    invalid_id_msg_key: str,
    header_key: str
) -> str:
    """Creates a final report message for the admin action."""
    reply_parts = []
    if success_count > 0:
        reply_parts.append(get_text(success_msg_key, language, count=success_count))

    errors = []
    for failed_id in failed_ids:
        errors.append(get_text(error_msg_key, language, telegram_id=failed_id))
    for invalid_entry in invalid_entries:
        errors.append(get_text(invalid_id_msg_key, language, telegram_id_str=invalid_entry))

    if errors:
        error_messages_formatted = "- " + "\n- ".join(errors)
        reply_parts.append(f"{get_text(header_key, language)}\n{error_messages_formatted}")

    if not reply_parts:
        # This fallback is if both success_count is 0 and errors list is empty.
        # The calling functions (handle_tt_..._admin_command) should ideally handle cases
        # where no valid IDs were provided to parse in the first place.
        return get_text("TT_NO_ACTION_PERFORMED", language)

    return "\n\n".join(reply_parts)


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
    command: CommandObject, # Use CommandObject for arguments
    session: AsyncSession,
    bot_language: str
):
    """Handles the /addadmin TeamTalk command."""
    # command.args will be a string like "12345 67890" or None
    valid_ids, invalid_entries = _parse_telegram_ids(command.args)

    if not valid_ids and not invalid_entries:
        tt_message.reply(get_text("TT_ADD_ADMIN_PROMPT_IDS", bot_language))
        return

    success_count = 0
    failed_action_ids = [] # IDs where add_admin returned False (e.g., already admin)

    for telegram_id in valid_ids:
        # Log attempt before execution for better traceability if _execute crashes
        logger.info(f"Attempting to add TG ID {telegram_id} as admin by TT admin {ttstr(tt_message.user.username)}.")
        if await _execute_admin_action_for_id(
            session=session,
            telegram_id=telegram_id,
            crud_function=add_admin, # Pass the actual add_admin function
            commands_to_set=ADMIN_COMMANDS
        ):
            success_count += 1
            logger.info(f"Successfully added TG ID {telegram_id} as admin and set commands.")
        else:
            failed_action_ids.append(telegram_id)
            logger.warning(f"Failed to add TG ID {telegram_id} as admin (e.g., already admin or DB error).")

    report_message = _create_admin_action_report(
        language=bot_language,
        success_count=success_count,
        failed_ids=failed_action_ids, # Pass IDs that failed the CRUD operation
        invalid_entries=invalid_entries, # Pass entries that were not valid IDs
        success_msg_key="TT_ADD_ADMIN_SUCCESS",
        error_msg_key="TT_ADD_ADMIN_ERROR_ALREADY_ADMIN", # For failed add_admin (e.g. already admin)
        invalid_id_msg_key="TT_ADD_ADMIN_ERROR_INVALID_ID", # For non-integer inputs
        header_key="TT_ADMIN_ERRORS_HEADER"
    )

    tt_message.reply(report_message)


@is_tt_admin
async def handle_tt_remove_admin_command(
    tt_message: TeamTalkMessage, *,
    command: CommandObject, # Use CommandObject for arguments
    session: AsyncSession,
    bot_language: str
):
    """Handles the /removeadmin TeamTalk command."""
    valid_ids, invalid_entries = _parse_telegram_ids(command.args)

    if not valid_ids and not invalid_entries:
        tt_message.reply(get_text("TT_REMOVE_ADMIN_PROMPT_IDS", bot_language))
        return

    success_count = 0
    failed_action_ids = [] # IDs where remove_admin_db returned False

    for telegram_id in valid_ids:
        # Log attempt before execution
        logger.info(f"Attempting to remove TG ID {telegram_id} as admin by TT admin {ttstr(tt_message.user.username)}.")
        if await _execute_admin_action_for_id(
            session=session,
            telegram_id=telegram_id,
            crud_function=remove_admin_db, # Pass the actual remove_admin_db function
            commands_to_set=USER_COMMANDS # Set user commands on successful removal
        ):
            success_count += 1
            logger.info(f"Successfully removed TG ID {telegram_id} as admin and set user commands.")
        else:
            failed_action_ids.append(telegram_id)
            logger.warning(f"Failed to remove TG ID {telegram_id} as admin (e.g., was not admin or DB error).")

    report_message = _create_admin_action_report(
        language=bot_language,
        success_count=success_count,
        failed_ids=failed_action_ids,
        invalid_entries=invalid_entries,
        success_msg_key="TT_REMOVE_ADMIN_SUCCESS",
        error_msg_key="TT_REMOVE_ADMIN_ERROR_NOT_FOUND", # For failed remove_admin_db (e.g. not an admin)
        invalid_id_msg_key="TT_ADD_ADMIN_ERROR_INVALID_ID", # Reused: for non-integer inputs
        header_key="TT_ADMIN_INFO_ERRORS_HEADER" # Specific header for remove command context
    )

    tt_message.reply(report_message)


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
