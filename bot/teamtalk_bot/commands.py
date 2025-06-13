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
from bot.language import get_translator
from bot.core.utils import build_help_message # Already refactored to take `_`
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
        # Expect `_` (translator) in kwargs instead of bot_language
        _ = kwargs.get("_")
        if not _: # Fallback if _ is not provided
            # If this fallback is hit often, it means `_` is not being passed correctly by the caller of decorated functions
            _ = get_translator(app_config.get("DEFAULT_LANG", "en")).gettext
            kwargs["_"] = _ # Ensure _ is in kwargs for the wrapped function if it was missing

        username = ttstr(tt_message.user.username)
        admin_username = app_config.get("ADMIN_USERNAME")

        if not admin_username or username != admin_username:
            logger.warning(
                f"Unauthorized admin command attempt by TT user {username} for function {func.__name__}."
            )
            tt_message.reply(_("You do not have permission to use this command.")) # TT_ADMIN_CMD_NO_PERMISSION
            return None

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
    _: callable,
    success_count: int,
    failed_ids: list[int],
    invalid_entries: list[str],
    success_msg_source: str, # English source string
    error_msg_source: str,   # English source string
    invalid_id_msg_source: str, # English source string
    header_source: str        # English source string
) -> str:
    """Creates a final report message for the admin action."""
    reply_parts = []
    if success_count > 0:
        reply_parts.append(_(success_msg_source).format(count=success_count))

    errors = []
    for failed_id in failed_ids:
        errors.append(_(error_msg_source).format(telegram_id=failed_id))
    for invalid_entry in invalid_entries:
        errors.append(_(invalid_id_msg_source).format(telegram_id_str=invalid_entry))

    if errors:
        error_messages_formatted = "- " + "\n- ".join(errors)
        reply_parts.append(f"{_(header_source)}\n{error_messages_formatted}")

    if not reply_parts:
        return _("No action was performed. Please check the IDs provided.") # TT_NO_ACTION_PERFORMED

    return "\n\n".join(reply_parts)


async def _manage_admin_ids(
    tt_message: TeamTalkMessage,
    command: CommandObject,
    session: AsyncSession,
    _: callable,
    crud_function: Callable[[AsyncSession, int], bool],
    commands_to_set: list[BotCommand],
    prompt_msg_key: str,
    success_msg_key: str,
    error_msg_key: str,
    invalid_id_msg_key: str,
    header_msg_key: str,
):
    """A generic handler for adding or removing admin IDs."""
    valid_ids, invalid_entries = _parse_telegram_ids(command.args)

    if not valid_ids and not invalid_entries:
        tt_message.reply(_(prompt_msg_key))
        return

    success_count = 0
    failed_action_ids = []

    for telegram_id in valid_ids:
        logger.info(f"Attempting to {crud_function.__name__} for TG ID {telegram_id} by TT admin {ttstr(tt_message.user.username)}.")
        if await _execute_admin_action_for_id(
            session=session, telegram_id=telegram_id, crud_function=crud_function, commands_to_set=commands_to_set
        ):
            success_count += 1
            logger.info(f"Successfully processed {crud_function.__name__} for TG ID {telegram_id} and set commands.")
        else:
            failed_action_ids.append(telegram_id)
            logger.warning(f"Failed to process {crud_function.__name__} for TG ID {telegram_id} (e.g., already in state or DB error).")

    report_message = _create_admin_action_report(
        _,
        success_count,
        failed_action_ids,
        invalid_entries,
        success_msg_key,
        error_msg_key,
        invalid_id_msg_key,
        header_msg_key
    )
    tt_message.reply(report_message)


async def _generate_and_reply_deeplink(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    _: callable,
    action: str,
    success_log_message: str,
    reply_text_source: str, # English source string
    error_reply_source: str,  # English source string
    payload: Optional[str] = None,
):
    """
    Helper function to generate a deeplink, log success, and reply to the TeamTalk message.
    Includes error handling.
    """
    sender_tt_username = ttstr(tt_message.user.username)
    try:
        token_val = await create_deeplink(
            session, action, payload=payload, expected_telegram_id=None
        )
        bot_info_val = await tg_bot_event.get_me() # Bot username for the deeplink
        deeplink_url_val = f"https://t.me/{bot_info_val.username}?start={token_val}"

        logger.info(success_log_message.format(token=token_val, sender_username=sender_tt_username))

        # The original TT_SUBSCRIBE_DEEPLINK_TEXT included {deeplink_url} but also mentioned {bot_username} and {tt_user_id}
        # The prompt's example for /sub is:
        # _("To subscribe to Telegram notifications and link your TeamTalk account for NOON, please use the following command with the bot @{bot_username} on Telegram:\n\n/start {token}\n\nYour TeamTalk User ID is: {tt_user_id}")
        # This is more complex than a simple reply_text_source.format(deeplink_url=...).
        # For now, I'll use the simpler source strings that match the old keys' direct purpose.
        if "{deeplink_url}" in reply_text_source: # Check if placeholder exists
             reply_text_val = _(reply_text_source).format(deeplink_url=deeplink_url_val)
        else: # If not, the source string is static (e.g. error message)
             reply_text_val = _(reply_text_source)

        tt_message.reply(reply_text_val)
    except Exception as e:
        logger.error(
            f"Error processing deeplink action {action} for TT user {sender_tt_username}: {e}",
            exc_info=True
        )
        tt_message.reply(_(error_reply_source))


async def handle_tt_subscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    _: callable
):
    sender_tt_username = ttstr(tt_message.user.username)
    # English Source for TT_SUBSCRIBE_DEEPLINK_TEXT: "Click this link to subscribe to notifications and link your TeamTalk account for NOON (link valid for 5 minutes):\n{deeplink_url}"
    # The prompt example is more detailed, but this matches the old key.
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        _=_,
        action=ACTION_SUBSCRIBE_AND_LINK_NOON,
        payload=sender_tt_username,
        success_log_message="Generated subscribe and link NOON deeplink {token} for TT user {sender_username}",
        reply_text_source="Click this link to subscribe to notifications and link your TeamTalk account for NOON (link valid for 5 minutes):\n{deeplink_url}",
        error_reply_source="An error occurred while processing the subscription request.",
    )


async def handle_tt_unsubscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    _: callable
):
    # English Source for TT_UNSUBSCRIBE_DEEPLINK_TEXT: "Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_url}"
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        _=_,
        action=ACTION_UNSUBSCRIBE,
        payload=None,
        success_log_message="Generated unsubscribe deeplink {token} for TT user {sender_username}",
        reply_text_source="Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_url}",
        error_reply_source="An error occurred while processing the unsubscription request.",
    )


@is_tt_admin # Passes `_` in kwargs
async def handle_tt_add_admin_command(
    tt_message: TeamTalkMessage, *,
    command: CommandObject,
    session: AsyncSession,
    _: callable
):
    await _manage_admin_ids(
        tt_message=tt_message,
        command=command,
        session=session,
        _=_,
        crud_function=add_admin,
        commands_to_set=ADMIN_COMMANDS,
        prompt_msg_key="Please provide Telegram IDs after the command. Example: /add_admin 12345678 98765432",
        success_msg_key="Successfully added {count} admin(s).",
        error_msg_key="ID {telegram_id} is already an admin or failed to add.",
        invalid_id_msg_key="'{telegram_id_str}' is not a valid numeric Telegram ID.",
        header_msg_key="Errors:\n- "
    )


@is_tt_admin # Passes `_` in kwargs
async def handle_tt_remove_admin_command(
    tt_message: TeamTalkMessage, *,
    command: CommandObject,
    session: AsyncSession,
    _: callable
):
    await _manage_admin_ids(
        tt_message=tt_message,
        command=command,
        session=session,
        _=_,
        crud_function=remove_admin_db,
        commands_to_set=USER_COMMANDS,
        prompt_msg_key="Please provide Telegram IDs after the command. Example: /remove_admin 12345678 98765432",
        success_msg_key="Successfully removed {count} admin(s).",
        error_msg_key="Admin with ID {telegram_id} not found.",
        invalid_id_msg_key="'{telegram_id_str}' is not a valid numeric Telegram ID.",
        header_msg_key="Info/Errors:\n- "
    )


async def handle_tt_help_command(
    tt_message: TeamTalkMessage,
    _: callable
):
    is_admin = False
    tt_username_str = ttstr(tt_message.user.username) if tt_message.user and hasattr(tt_message.user, 'username') else None
    admin_username_from_config = app_config.get("ADMIN_USERNAME")

    if tt_username_str and admin_username_from_config and tt_username_str == admin_username_from_config:
        is_admin = True # This user is the main TeamTalk admin specified in config

    # build_help_message expects: _, platform, is_admin (TT server admin), is_bot_admin (bot admin)
    help_text = build_help_message(_, "teamtalk", is_admin, is_admin)
    await send_long_tt_reply(tt_message.reply, help_text)


async def handle_tt_unknown_command(
    tt_message: TeamTalkMessage,
    _: callable
):
    reply_text_val = _("Unknown command. Available commands: /sub, /unsub, /add_admin, /remove_admin, /help.") # TT_UNKNOWN_COMMAND
    tt_message.reply(reply_text_val)
    logger.warning(f"Received unknown TT command from {ttstr(tt_message.user.username)}: {tt_message.content[:100]}")
