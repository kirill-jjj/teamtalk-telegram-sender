import logging
import functools
from typing import Optional, Callable, List
from aiogram.filters import CommandObject
from aiogram.types import BotCommandScopeChat, BotCommand
from sqlalchemy.ext.asyncio import AsyncSession

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
        # The translator `_` is expected as the first positional argument after `tt_message`,
        # so it will be in `args[0]`.
        # If `args` is empty, an IndexError will occur, highlighting a programming error
        # in how the decorated function is called, which is intended.
        _ = args[0]

        username = ttstr(tt_message.user.username)
        admin_username = app_config.ADMIN_USERNAME

        if not admin_username or username != admin_username:
            logger.warning(
                f"Unauthorized admin command attempt by TT user {username} for function {func.__name__}."
            )
            tt_message.reply(_("You do not have permission to use this command."))
            return None

        # The wrapped function's signature will be:
        # async def some_func(tt_message: TeamTalkMessage, _: callable, *, kwarg1=val1, ...)
        # `*args` here will correctly pass the translator as the second positional argument to `func`.
        # `**kwargs` will pass any keyword arguments.
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
    success_msg_source: str,
    error_msg_source: str,
    invalid_id_msg_source: str,
    header_source: str
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
        bot_info = await tg_bot_event.get_me()
        deeplink_url = f"https://t.me/{bot_info.username}?start={token}"

        logger.info(success_log_message.format(token=token, sender_username=sender_tt_username))

        if "{deeplink_url}" in reply_text_source: # Check if placeholder exists
             reply_text = _(reply_text_source).format(deeplink_url=deeplink_url)
        else: # If not, the source string is static (e.g. error message)
             reply_text = _(reply_text_source)

        tt_message.reply(reply_text)
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
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        _=_,
        action=DeeplinkAction.SUBSCRIBE_AND_LINK_NOON,
        payload=sender_tt_username,
        success_log_message="Generated subscribe and link NOON deeplink {token} for TT user {sender_username}",
        reply_text_source=_("Click this link to subscribe to notifications and link your TeamTalk account for NOON (link valid for 5 minutes):\n{deeplink_url}"),
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


@is_tt_admin # Comment needs update, but not part of this task
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
        success_msg_key=_("Successfully added {count} admin(s)."),
        error_msg_key=_("ID {telegram_id} is already an admin or failed to add."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric Telegram ID."),
        header_msg_key=_("Errors:\n- ")
    )


@is_tt_admin # Comment needs update, but not part of this task
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
        success_msg_key=_("Successfully removed {count} admin(s)."),
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
