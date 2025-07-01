import logging
import functools
from typing import Optional, Callable, List
from aiogram.filters import CommandObject
from aiogram.types import BotCommandScopeChat, BotCommand
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.exceptions import TelegramAPIError

import pytalk
from pytalk.message import Message as TeamTalkMessage

from bot.config import app_config
from bot.language import get_translator
from bot.core.utils import build_help_message
from bot.database.crud import create_deeplink, add_admin, remove_admin_db
from bot.telegram_bot.bot_instances import tg_bot_event # For get_me()
from bot.telegram_bot.commands import ADMIN_COMMANDS, USER_COMMANDS
from bot.teamtalk_bot.utils import send_long_tt_reply
from bot.core.enums import DeeplinkAction

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


# Decorator for TeamTalk admin commands
def is_tt_admin(func):
    @functools.wraps(func)
    async def wrapper(tt_message: TeamTalkMessage, *args, **kwargs):
        _ = kwargs.get('_')
        if not _ or not callable(_):
            raise TypeError("Translator function '_' was not provided as a keyword argument to the decorated function.")

        username = ttstr(tt_message.user.username)
        admin_username = app_config.ADMIN_USERNAME

        if not admin_username or username != admin_username:
            logger.warning(
                f"Unauthorized admin command attempt by TT user {username} for function {func.__name__}."
            )
            tt_message.reply(_("You do not have permission to use this command."))
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
    crud_function: Callable[[AsyncSession, int], bool],
    commands_to_set: list[BotCommand]
) -> bool:
    """Executes a CRUD function for a single ID and sets Telegram commands on success."""
    if await crud_function(session, telegram_id):
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
    success_message_direct: str,
    error_msg_source: str,
    invalid_id_msg_source: str,
    header_source: str
) -> str:
    """Creates a final report message for the admin action."""
    reply_parts = []
    if success_count > 0:
        reply_parts.append(success_message_direct)

    errors = []
    for failed_id in failed_ids:
        errors.append(_(error_msg_source).format(telegram_id=failed_id))
    for invalid_entry in invalid_entries:
        errors.append(_(invalid_id_msg_source).format(telegram_id_str=invalid_entry))

    if errors:
        error_messages_formatted = "- " + "\n- ".join(errors)
        reply_parts.append(f"{_(header_source)}\n{error_messages_formatted}")

    if not reply_parts:
        return _("No action was performed. Please check the IDs provided.")

    return "\n\n".join(reply_parts)


async def _manage_admin_ids(
    tt_message: TeamTalkMessage,
    command: CommandObject,
    session: AsyncSession,
    _: callable,
    crud_function: Callable[[AsyncSession, int], bool],
    commands_to_set: list[BotCommand],
    prompt_msg_key: str,
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

    success_message_formatted = ""
    if crud_function is add_admin:
        success_message_formatted = _.ngettext("Successfully added {count} admin.", "Successfully added {count} admins.", success_count).format(count=success_count)
    elif crud_function is remove_admin_db:
        success_message_formatted = _.ngettext("Successfully removed {count} admin.", "Successfully removed {count} admins.", success_count).format(count=success_count)

    report_message = _create_admin_action_report(
        _,
        success_count,
        failed_action_ids,
        invalid_entries,
        success_message_direct=success_message_formatted,
        error_msg_source=error_msg_key,
        invalid_id_msg_source=invalid_id_msg_key,
        header_source=header_msg_key
    )
    tt_message.reply(report_message)


async def _generate_and_reply_deeplink(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    _: callable,
    action: DeeplinkAction,
    success_log_message: str,
    reply_text_source: str,
    error_reply_source: str,
    payload: Optional[str] = None,
):
    """
    Helper function to generate a deeplink, log success, and reply to the TeamTalk message.
    Includes error handling.
    """
    sender_tt_username = ttstr(tt_message.user.username)
    try:
        token = await create_deeplink(
            session, action, payload=payload, expected_telegram_id=None
        )
        bot_info = await tg_bot_event.get_me() # This can raise TelegramAPIError
        deeplink_url = f"https://t.me/{bot_info.username}?start={token}"

        logger.info(success_log_message.format(token=token, sender_username=sender_tt_username))

        if "{deeplink_url}" in reply_text_source:
             reply_text = _(reply_text_source).format(deeplink_url=deeplink_url)
        else:
             reply_text = _(reply_text_source)

        tt_message.reply(reply_text) # Pytalk call

    except TelegramAPIError as e_tg:
        logger.error(
            f"Telegram API error processing deeplink action {action} for TT user {sender_tt_username}: {e_tg}",
            exc_info=True
        )
        # Try to reply with a specific Telegram error if possible, else generic.
        # Note: If tt_message.reply fails here, it will go to the outer generic Exception.
        try:
            tt_message.reply(_("Error communicating with Telegram. Please try again later."))
        except Exception as e_reply_tg:
            logger.error(f"Failed to send Telegram API error reply to TT user {sender_tt_username}: {e_reply_tg}")

    except Exception as e: # General fallback for other errors (deeplink creation, tt_message.reply, etc.)
        logger.error(
            f"Generic error processing deeplink action {action} for TT user {sender_tt_username}: {e}",
            exc_info=True
        )
        try:
            tt_message.reply(_(error_reply_source)) # Use the provided generic error source
        except Exception as e_reply_generic:
            logger.error(f"Failed to send generic error reply to TT user {sender_tt_username}: {e_reply_generic}")


async def handle_tt_subscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    _: callable
):
    sender_tt_username = ttstr(tt_message.user.username)
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        _=_,
        action=DeeplinkAction.SUBSCRIBE,
        payload=sender_tt_username,
        success_log_message="Generated subscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_("Click this link to subscribe to notifications (link valid for 5 minutes):\n{deeplink_url}"),
        error_reply_source=_("An error occurred while processing the subscription request."),
    )


async def handle_tt_unsubscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    _: callable
):
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        _=_,
        action=DeeplinkAction.UNSUBSCRIBE,
        payload=None,
        success_log_message="Generated unsubscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_("Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_url}"),
        error_reply_source=_("An error occurred while processing the unsubscription request."),
    )


@is_tt_admin
async def handle_tt_add_admin_command(
    tt_message: TeamTalkMessage,
    _: callable, *,
    command: CommandObject,
    session: AsyncSession
):
    # Dummy call for pybabel extraction
    if False:
        _.ngettext("Successfully added {count} admin.", "Successfully added {count} admins.", 1)

    await _manage_admin_ids(
        tt_message=tt_message,
        command=command,
        session=session,
        _=_,
        crud_function=add_admin,
        commands_to_set=ADMIN_COMMANDS,
        prompt_msg_key=_("Please provide Telegram IDs after the command. Example: /add_admin 12345678 98765432"),
        error_msg_key=_("ID {telegram_id} is already an admin or failed to add."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric Telegram ID."),
        header_msg_key=_("Errors:\n- ")
    )


@is_tt_admin
async def handle_tt_remove_admin_command(
    tt_message: TeamTalkMessage,
    _: callable, *,
    command: CommandObject,
    session: AsyncSession
):
    # Dummy call for pybabel extraction
    if False:
        _.ngettext("Successfully removed {count} admin.", "Successfully removed {count} admins.", 1)

    await _manage_admin_ids(
        tt_message=tt_message,
        command=command,
        session=session,
        _=_,
        crud_function=remove_admin_db,
        commands_to_set=USER_COMMANDS,
        prompt_msg_key=_("Please provide Telegram IDs after the command. Example: /remove_admin 12345678 98765432"),
        error_msg_key=_("Admin with ID {telegram_id} not found."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric Telegram ID."),
        header_msg_key=_("Info/Errors:\n- ")
    )


async def handle_tt_help_command(
    tt_message: TeamTalkMessage,
    _: callable
):
    is_admin = False
    tt_username_str = ttstr(tt_message.user.username) if tt_message.user and hasattr(tt_message.user, 'username') else None
    admin_username_from_config = app_config.ADMIN_USERNAME

    if tt_username_str and admin_username_from_config and tt_username_str == admin_username_from_config:
        is_admin = True # This user is the main TeamTalk admin specified in config

    # build_help_message expects: _, platform, is_admin (TT server admin), is_bot_admin (bot admin)
    help_text = build_help_message(_, "teamtalk", is_admin, is_admin)
    await send_long_tt_reply(tt_message.reply, help_text)


async def handle_tt_unknown_command(
    tt_message: TeamTalkMessage,
    _: callable
):
    reply_text = _("Unknown command. Available commands: /sub, /unsub, /add_admin, /remove_admin, /help.")
    tt_message.reply(reply_text)
    logger.warning(f"Received unknown TT command from {ttstr(tt_message.user.username)}: {tt_message.content[:100]}")
