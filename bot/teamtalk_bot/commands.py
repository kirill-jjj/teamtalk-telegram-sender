import logging
import functools
import gettext
from typing import Optional, Callable, Any, TYPE_CHECKING
# from aiogram.filters import CommandObject # Not used directly by these handlers anymore
from pydantic import BaseModel, model_validator, Field
from aiogram.types import BotCommandScopeChat, BotCommand
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from aiogram.exceptions import TelegramAPIError
from pytalk.exceptions import TeamTalkException

import pytalk
from pytalk.message import Message as TeamTalkMessage

from bot.core.utils import build_help_message
from bot.database.crud import create_deeplink, add_admin, remove_admin_db
from bot.telegram_bot.commands import get_admin_commands, get_user_commands
from bot.teamtalk_bot.utils import send_long_tt_reply
from bot.core.enums import DeeplinkAction

if TYPE_CHECKING:
    from sender import Application # For type hinting app instance
    # from bot.teamtalk_bot.connection import TeamTalkConnection # Already imported if needed for direct pass

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


class AdminIdArgs(BaseModel): # This model seems fine as is
    valid_ids: list[int] = Field(default_factory=list)
    invalid_entries: list[str] = Field(default_factory=list)

    @model_validator(mode='before')
    @classmethod
    def parse_str_to_dict(cls, data: Any) -> dict[str, list]:
        if data is None or not isinstance(data, str):
            return {"valid_ids": [], "invalid_entries": []}
        command_args_str = data.strip()
        if not command_args_str:
            return {"valid_ids": [], "invalid_entries": []}
        valid_ids = []
        invalid_entries = []
        parts = command_args_str.split()
        for part in parts:
            if part.isdigit(): valid_ids.append(int(part))
            else: invalid_entries.append(part)
        return {"valid_ids": valid_ids, "invalid_entries": invalid_entries}


def is_tt_admin(func):
    @functools.wraps(func)
    async def wrapper(tt_message: TeamTalkMessage, *args, **kwargs):
        # app instance should be in kwargs, passed from Application.on_pytalk_message
        app: "Application" = kwargs.get('app')
        if not app:
            raise ValueError("Application instance 'app' not found in kwargs for is_tt_admin decorator.")

        translator = kwargs.get('translator')
        if not translator or not isinstance(translator, gettext.GNUTranslations):
             raise TypeError("Translator object 'translator' was not provided as a keyword argument.")
        _ = translator.gettext

        username = ttstr(tt_message.user.username)
        admin_username = app.app_config.ADMIN_USERNAME # Use app.app_config

        if not admin_username or username != admin_username:
            logger.warning(f"Unauthorized admin command attempt by TT user {username} for function {func.__name__}.")
            tt_message.reply(_("You are not authorized to perform this action."))
            return None
        return await func(tt_message, *args, **kwargs)
    return wrapper


async def _execute_admin_action_for_id(
    session: AsyncSession,
    telegram_id: int,
    crud_function: Callable[[AsyncSession, int], bool],
    commands_to_set_getter: Callable[[Callable[[str], str]], list[BotCommand]],
    translator: gettext.GNUTranslations,
    app: "Application" # Pass app instance
) -> bool:
    _ = translator.gettext
    if await crud_function(session, telegram_id):
        try:
            commands = commands_to_set_getter(_)
            # Use app's Telegram bot instance
            await app.tg_bot_event.set_my_commands(
                commands=commands,
                scope=BotCommandScopeChat(chat_id=telegram_id)
            )
        except TelegramAPIError as e:
            logger.error(f"Failed to set commands for TG ID {telegram_id} after {crud_function.__name__}: {e}")
        return True
    return False


def _create_admin_action_report( # This helper is fine as is
    translator: gettext.GNUTranslations,
    success_count: int,
    failed_ids: list[int],
    invalid_entries: list[str],
    success_message_direct: str,
    error_msg_source: str,
    invalid_id_msg_source: str,
    header_source: str
) -> str:
    _ = translator.gettext
    reply_parts = []
    if success_count > 0: reply_parts.append(success_message_direct)
    errors = []
    for failed_id in failed_ids: errors.append(_(error_msg_source).format(telegram_id=failed_id))
    for invalid_entry in invalid_entries: errors.append(_(invalid_id_msg_source).format(telegram_id_str=invalid_entry))
    if errors:
        header = _(header_source)
        error_list_str = "\n".join(f"- {error}" for error in errors)
        reply_parts.append(f"{header}\n{error_list_str}")
    if not reply_parts: return _("No action was performed. Please check the IDs provided.")
    return "\n\n".join(reply_parts)


async def _manage_admin_ids(
    tt_message: TeamTalkMessage,
    args_str: Optional[str],
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    crud_function: Callable[[AsyncSession, int], bool],
    commands_to_set_getter: Callable[[Callable[[str], str]], list[BotCommand]],
    prompt_msg_key: str,
    error_msg_key: str,
    invalid_id_msg_key: str,
    header_msg_key: str,
    app: "Application" # Pass app instance
):
    _ = translator.gettext
    args = AdminIdArgs.model_validate(args_str)
    if not args.valid_ids and not args.invalid_entries:
        tt_message.reply(_(prompt_msg_key))
        return

    success_count = 0
    failed_action_ids = []
    for telegram_id in args.valid_ids:
        logger.info(f"Attempting to {crud_function.__name__} for TG ID {telegram_id} by TT admin {ttstr(tt_message.user.username)}.")
        if await _execute_admin_action_for_id(
            session=session,
            telegram_id=telegram_id,
            crud_function=crud_function,
            commands_to_set_getter=commands_to_set_getter,
            translator=translator,
            app=app # Pass app
        ):
            success_count += 1
            # Update app's admin cache if successful
            if crud_function is add_admin: app.admin_ids_cache.add(telegram_id)
            elif crud_function is remove_admin_db: app.admin_ids_cache.discard(telegram_id)
            logger.info(f"Successfully processed {crud_function.__name__} for TG ID {telegram_id} and set commands.")
        else:
            failed_action_ids.append(telegram_id)
            logger.warning(f"Failed to process {crud_function.__name__} for TG ID {telegram_id} (e.g., already in state or DB error).")

    success_message_formatted = ""
    if crud_function is add_admin:
        success_message_formatted = translator.ngettext("Successfully added {count} admin.", "Successfully added {count} admins.", success_count).format(count=success_count)
    elif crud_function is remove_admin_db:
        success_message_formatted = translator.ngettext("Successfully removed {count} admin.", "Successfully removed {count} admins.", success_count).format(count=success_count)

    report_message = _create_admin_action_report(
        translator, success_count, failed_action_ids, args.invalid_entries,
        success_message_direct=success_message_formatted,
        error_msg_source=error_msg_key, invalid_id_msg_source=invalid_id_msg_key,
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
    app: "Application", # Pass app instance
    payload: Optional[str] = None,
):
    sender_tt_username = ttstr(tt_message.user.username)
    try:
        token = await create_deeplink(
            session,
            action,
            app.app_config.DEEPLINK_TTL_SECONDS, # Pass TTL
            payload=payload,
            expected_telegram_id=None
        )
        # Use app's Telegram bot instance
        bot_info = await app.tg_bot_event.get_me()
        deeplink_url = f"https://t.me/{bot_info.username}?start={token}"
        logger.info(success_log_message.format(token=token, sender_username=sender_tt_username))
        reply_text = _(reply_text_source).format(deeplink_url=deeplink_url) if "{deeplink_url}" in reply_text_source else _(reply_text_source)
        tt_message.reply(reply_text)
    except TelegramAPIError as e_tg:
        logger.error(f"Telegram API error processing deeplink action {action} for TT user {sender_tt_username}: {e_tg}", exc_info=True)
        try: tt_message.reply(_("An error occurred. Please try again later."))
        except Exception as e_reply: logger.error(f"Failed to send Telegram API error reply to TT user {sender_tt_username}: {e_reply}")
    except SQLAlchemyError as e_db:
        logger.error(f"Database error creating deeplink for action {action} for TT user {sender_tt_username}: {e_db}", exc_info=True)
        try: tt_message.reply(_("An error occurred. Please try again later."))
        except Exception as e_reply: logger.error(f"Failed to send DB error reply to TT user {sender_tt_username}: {e_reply}")
    except TeamTalkException as e_tt:
        logger.error(f"TeamTalk error processing deeplink action {action} for TT user {sender_tt_username}: {e_tt}", exc_info=True)
        try: tt_message.reply(_("An error occurred. Please try again later."))
        except Exception as e_reply: logger.error(f"Failed to send TT error reply to TT user {sender_tt_username}: {e_reply}")


async def handle_tt_subscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    _: callable,
    app: "Application", # Add app
    connection: "TeamTalkConnection" # Add connection (though not directly used by this one)
):
    sender_tt_username = ttstr(tt_message.user.username)
    await _generate_and_reply_deeplink(
        tt_message=tt_message, session=session, _=_,
        action=DeeplinkAction.SUBSCRIBE, payload=sender_tt_username,
        success_log_message="Generated subscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_("Click this link to subscribe to notifications (link valid for 5 minutes):\n{deeplink_url}"),
        error_reply_source=_("An error occurred while processing the subscription request."),
        app=app # Pass app
    )


async def handle_tt_unsubscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    _: callable,
    app: "Application", # Add app
    connection: "TeamTalkConnection" # Add connection
):
    await _generate_and_reply_deeplink(
        tt_message=tt_message, session=session, _=_,
        action=DeeplinkAction.UNSUBSCRIBE, payload=None,
        success_log_message="Generated unsubscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_("Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_url}"),
        error_reply_source=_("An error occurred while processing the unsubscription request."),
        app=app # Pass app
    )


@is_tt_admin
async def handle_tt_add_admin_command(
    tt_message: TeamTalkMessage,
    translator: gettext.GNUTranslations,
    session: AsyncSession,
    app: "Application", # Added app, will be in kwargs for decorator
    connection: "TeamTalkConnection", # Added connection
    *, # Force args_str to be keyword-only if it was not already
    args_str: Optional[str]
):
    if False: translator.ngettext("Successfully added {count} admin.", "Successfully added {count} admins.", 1) # For pybabel
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message, args_str=args_str, session=session, translator=translator,
        crud_function=add_admin, commands_to_set_getter=get_admin_commands,
        prompt_msg_key=_("Please provide Telegram IDs after the command. Example: /add_admin 12345678 98765432"),
        error_msg_key=_("ID {telegram_id} is already an admin or failed to add."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric Telegram ID."),
        header_msg_key=_("Action Results:"),
        app=app # Pass app
    )


@is_tt_admin
async def handle_tt_remove_admin_command(
    tt_message: TeamTalkMessage,
    translator: gettext.GNUTranslations,
    session: AsyncSession,
    app: "Application", # Added app
    connection: "TeamTalkConnection", # Added connection
    *,
    args_str: Optional[str]
):
    if False: translator.ngettext("Successfully removed {count} admin.", "Successfully removed {count} admins.", 1) # For pybabel
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message, args_str=args_str, session=session, translator=translator,
        crud_function=remove_admin_db, commands_to_set_getter=get_user_commands,
        prompt_msg_key=_("Please provide Telegram IDs after the command. Example: /remove_admin 12345678 98765432"),
        error_msg_key=_("Admin with ID {telegram_id} not found."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric Telegram ID."),
        header_msg_key=_("Action Results:"),
        app=app # Pass app
    )


async def handle_tt_help_command(
    tt_message: TeamTalkMessage,
    _: callable, # This is gettext from the translator passed by Application.on_pytalk_message
    app: "Application", # Add app
    connection: "TeamTalkConnection" # Add connection
):
    is_main_tt_admin = False
    tt_username_str = ttstr(tt_message.user.username) if tt_message.user and hasattr(tt_message.user, 'username') else None
    admin_username_from_config = app.app_config.ADMIN_USERNAME # Use app.app_config

    if tt_username_str and admin_username_from_config and tt_username_str == admin_username_from_config:
        is_main_tt_admin = True

    help_text = build_help_message(_, "teamtalk", is_telegram_admin=False, is_teamtalk_admin=is_main_tt_admin)
    # send_long_tt_reply might need connection.instance if it interacts with TT features beyond simple reply
    # For now, assuming tt_message.reply is sufficient.
    await send_long_tt_reply(tt_message.reply, help_text)


async def handle_tt_unknown_command(
    tt_message: TeamTalkMessage,
    _: callable,
    app: "Application", # Add app (though not used yet)
    connection: "TeamTalkConnection" # Add connection (though not used yet)
):
    reply_text = _("Unknown command. Available commands: /sub, /unsub, /add_admin, /remove_admin, /help.")
    tt_message.reply(reply_text)
    logger.warning(f"Received unknown TT command from {ttstr(tt_message.user.username)} on server {connection.server_info.host if connection else 'Unknown'}: {tt_message.content[:100]}")
