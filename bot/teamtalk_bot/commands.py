"""Command handlers for the TeamTalk bot interface."""

from __future__ import annotations

from collections.abc import Callable
import functools
import gettext
import logging
from typing import TYPE_CHECKING, Any

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat
from pydantic import BaseModel, Field, model_validator
import pytalk
from pytalk.exceptions import TeamTalkException
from pytalk.message import Message as TeamTalkMessage
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession # Changed to SQLModel's AsyncSession

from bot.core.enums import DeeplinkAction
from bot.core.utils import build_help_message
from bot.database.crud import add_admin, create_deeplink, remove_admin_db
from bot.teamtalk_bot.utils import send_long_tt_reply
from bot.telegram_bot.commands import get_admin_commands, get_user_commands

if TYPE_CHECKING:
    from bot.services_container import Services  # For type hinting app instance
    from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


class AdminIdArgs(BaseModel):
    """Parses and validates arguments for admin commands that take Telegram IDs."""

    valid_ids: list[int] = Field(default_factory=list)
    invalid_entries: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def parse_str_to_dict(cls, data: Any) -> dict[str, list]:
        """Parses a string of space-separated arguments into valid IDs and invalid entries."""
        if data is None or not isinstance(data, str):
            return {"valid_ids": [], "invalid_entries": []}
        command_args_str = data.strip()
        if not command_args_str:
            return {"valid_ids": [], "invalid_entries": []}
        valid_ids = []
        invalid_entries = []
        parts = command_args_str.split()
        for part in parts:
            if part.isdigit():
                valid_ids.append(int(part))
            else:
                invalid_entries.append(part)
        return {"valid_ids": valid_ids, "invalid_entries": invalid_entries}


def is_tt_admin(func: Callable) -> Callable:
    """Decorator to check if a TeamTalk user is the configured main admin."""

    @functools.wraps(func)
    async def wrapper(tt_message: TeamTalkMessage, *args, **kwargs):
        services: Services = kwargs.get("services")  # Changed to services
        if not services:
            raise ValueError("Services instance 'services' not found in kwargs for is_tt_admin decorator.")

        translator = kwargs.get("translator")
        if not translator or not isinstance(translator, gettext.GNUTranslations):
            raise TypeError("Translator object 'translator' was not provided as a keyword argument.")
        _ = translator.gettext

        username = ttstr(tt_message.user.username)
        admin_username = services.config.general.admin_username  # Use services.config

        if not admin_username or username != admin_username:
            logger.warning("Unauthorized admin command attempt by TT user %s for function %s.", username, func.__name__)
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
    services: Services,
) -> bool:
    _ = translator.gettext
    if await crud_function(session, telegram_id):
        try:
            commands = commands_to_set_getter(_)
            # Use services.bot_event
            await services.bot_event.set_my_commands(commands=commands, scope=BotCommandScopeChat(chat_id=telegram_id))
        except TelegramAPIError as e:
            logger.error("Failed to set commands for TG ID %s after %s: %s", telegram_id, crud_function.__name__, e)
        return True
    return False


def _create_admin_action_report(  # This helper is fine as is
    translator: gettext.GNUTranslations,
    success_count: int,
    failed_ids: list[int],
    invalid_entries: list[str],
    success_message_direct: str,
    error_msg_source: str,
    invalid_id_msg_source: str,
    header_source: str,
) -> str:
    _ = translator.gettext
    reply_parts = []
    if success_count > 0:
        reply_parts.append(success_message_direct)
    errors = []
    for failed_id in failed_ids:
        errors.append(_(error_msg_source).format(telegram_id=failed_id))
    for invalid_entry in invalid_entries:
        errors.append(_(invalid_id_msg_source).format(telegram_id_str=invalid_entry))
    if errors:
        header = _(header_source)
        error_list_str = "\n".join(f"- {error}" for error in errors)
        reply_parts.append(f"{header}\n{error_list_str}")
    if not reply_parts:
        return _("No action was performed. Please check the IDs provided.")
    return "\n\n".join(reply_parts)


async def _manage_admin_ids(
    tt_message: TeamTalkMessage,
    args_str: str | None,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    crud_function: Callable[[AsyncSession, int], bool],
    commands_to_set_getter: Callable[[Callable[[str], str]], list[BotCommand]],
    prompt_msg_key: str,
    error_msg_key: str,
    invalid_id_msg_key: str,
    header_msg_key: str,
    services: Services,
):
    _ = translator.gettext
    args = AdminIdArgs.model_validate(args_str)
    if not args.valid_ids and not args.invalid_entries:
        tt_message.reply(_(prompt_msg_key))
        return

    success_count = 0
    failed_action_ids = []
    for telegram_id in args.valid_ids:
        logger.info(
            "Attempting to %s for TG ID %s by TT admin %s.",
            crud_function.__name__,
            telegram_id,
            ttstr(tt_message.user.username),
        )
        if await _execute_admin_action_for_id(
            session=session,
            telegram_id=telegram_id,
            crud_function=crud_function,
            commands_to_set_getter=commands_to_set_getter,
            translator=translator,
            services=services,  # Pass services
        ):
            success_count += 1
            # Update services.admin_ids_cache if successful
            if crud_function is add_admin:
                services.admin_ids_cache.add(telegram_id)
            elif crud_function is remove_admin_db:
                services.admin_ids_cache.discard(telegram_id)
            logger.info("Successfully processed %s for TG ID %s and set commands.", crud_function.__name__, telegram_id)
        else:
            failed_action_ids.append(telegram_id)
            logger.warning(
                "Failed to process %s for TG ID %s (e.g., already in state or DB error).",
                crud_function.__name__,
                telegram_id,
            )

    success_message_formatted = ""
    if crud_function is add_admin:
        success_message_formatted = translator.ngettext(
            "Successfully added {count} admin.", "Successfully added {count} admins.", success_count
        ).format(count=success_count)
    elif crud_function is remove_admin_db:
        success_message_formatted = translator.ngettext(
            "Successfully removed {count} admin.", "Successfully removed {count} admins.", success_count
        ).format(count=success_count)

    report_message = _create_admin_action_report(
        translator,
        success_count,
        failed_action_ids,
        args.invalid_entries,
        success_message_direct=success_message_formatted,
        error_msg_source=error_msg_key,
        invalid_id_msg_source=invalid_id_msg_key,
        header_source=header_msg_key,
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
    services: Services,
    payload: str | None = None,
):
    sender_tt_username = ttstr(tt_message.user.username)
    try:
        token = await create_deeplink(
            session,
            action,
            services.config.operational_parameters.deeplink_ttl_seconds,  # Use services.config
            payload=payload,
            expected_telegram_id=None,
        )
        # Use services.bot_event
        bot_info = await services.bot_event.get_me()
        deeplink_url = f"https://t.me/{bot_info.username}?start={token}"
        logger.info("%s Token: %s, User: %s", success_log_message, token, sender_tt_username)
        if "{deeplink_url}" in reply_text_source:
            reply_text = _(reply_text_source).format(deeplink_url=deeplink_url)
        else:
            reply_text = _(reply_text_source)
        tt_message.reply(reply_text)
    except TelegramAPIError as e_tg:
        logger.exception(
            "Telegram API error processing deeplink action %s for TT user %s: %s",
            action,
            sender_tt_username,
            e_tg,
        )
        try:
            tt_message.reply(_("An error occurred. Please try again later."))
        except Exception as e_reply:
            logger.error("Failed to send Telegram API error reply to TT user %s: %s", sender_tt_username, e_reply)
    except SQLAlchemyError as e_db:
        logger.exception(
            "Database error creating deeplink for action %s for TT user %s: %s",
            action,
            sender_tt_username,
            e_db,
        )
        try:
            tt_message.reply(_("An error occurred. Please try again later."))
        except Exception as e_reply:
            logger.error("Failed to send DB error reply to TT user %s: %s", sender_tt_username, e_reply)
    except TeamTalkException as e_tt:
        logger.exception(
            "TeamTalk error processing deeplink action %s for TT user %s: %s",
            action,
            sender_tt_username,
            e_tt,
        )
        try:
            tt_message.reply(_("An error occurred. Please try again later."))
        except Exception as e_reply:
            logger.error("Failed to send TT error reply to TT user %s: %s", sender_tt_username, e_reply)


async def handle_tt_subscribe_command(
    tt_message: TeamTalkMessage, session: AsyncSession, _: callable, services: Services, connection: TeamTalkConnection
):
    """Handles the /sub command from a TeamTalk user.

    Generates a subscription deeplink and replies to the user.
    """
    sender_tt_username = ttstr(tt_message.user.username)
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        _=_,
        action=DeeplinkAction.SUBSCRIBE,
        payload=sender_tt_username,
        success_log_message="Generated subscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_(
            "Click this link to subscribe to notifications (link valid for 5 minutes):\n{deeplink_url}"
        ),
        error_reply_source=_("An error occurred. Please try again later."),
        services=services,  # Pass services
    )


async def handle_tt_unsubscribe_command(
    tt_message: TeamTalkMessage, session: AsyncSession, _: callable, services: Services, connection: TeamTalkConnection
):
    """Handles the /unsub command from a TeamTalk user.

    Generates an unsubscription deeplink and replies to the user.
    """
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        _=_,
        action=DeeplinkAction.UNSUBSCRIBE,
        payload=None,
        success_log_message="Generated unsubscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_(
            "Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_url}"
        ),
        error_reply_source=_("An error occurred. Please try again later."),
        services=services,  # Pass services
    )


@is_tt_admin
async def handle_tt_add_admin_command(
    tt_message: TeamTalkMessage,
    translator: gettext.GNUTranslations,
    session: AsyncSession,
    services: Services,  # will be in kwargs for decorator
    connection: TeamTalkConnection,
    *,
    args_str: str | None,
):
    """Handles the /add_admin command from a TeamTalk admin.

    Adds specified Telegram IDs as bot administrators.
    """
    # The following line is a placeholder for ngettext extraction by pybabel or similar tools.
    # It ensures that the singular and plural forms are available for translation.
    # It is not meant to be executed directly in this form.
    if False:
        translator.ngettext("Successfully added {count} admin.", "Successfully added {count} admins.", 1)
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message,
        args_str=args_str,
        session=session,
        translator=translator,
        crud_function=add_admin,
        commands_to_set_getter=get_admin_commands,
        prompt_msg_key=_("Please provide Telegram IDs after the command. Example: /add_admin 12345678 98765432"),
        error_msg_key=_("ID {telegram_id} is already an admin or failed to add."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric Telegram ID."),
        header_msg_key=_("Action Results:"),
        services=services,  # Pass services
    )


@is_tt_admin
async def handle_tt_remove_admin_command(
    tt_message: TeamTalkMessage,
    translator: gettext.GNUTranslations,
    session: AsyncSession,
    services: Services,
    connection: TeamTalkConnection,
    *,
    args_str: str | None,
):
    """Handles the /remove_admin command from a TeamTalk admin.

    Removes bot administrator privileges from specified Telegram IDs.
    """
    # Placeholder for ngettext extraction
    if False:
        translator.ngettext("Successfully removed {count} admin.", "Successfully removed {count} admins.", 1)
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message,
        args_str=args_str,
        session=session,
        translator=translator,
        crud_function=remove_admin_db,
        commands_to_set_getter=get_user_commands,
        prompt_msg_key=_("Please provide Telegram IDs after the command. Example: /remove_admin 12345678 98765432"),
        error_msg_key=_("Admin with ID {telegram_id} not found."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric Telegram ID."),
        header_msg_key=_("Action Results:"),
        services=services,  # Pass services
    )


async def handle_tt_help_command(
    tt_message: TeamTalkMessage, _: callable, services: Services, connection: TeamTalkConnection
):
    """Handles the /help command from a TeamTalk user.

    Sends a help message tailored to the user's admin status.
    """
    is_main_tt_admin = False
    tt_username_str = None
    if tt_message.user and hasattr(tt_message.user, "username"):
        tt_username_str = ttstr(tt_message.user.username)
    admin_username_from_config = services.config.general.admin_username  # Use services.config

    if tt_username_str and admin_username_from_config and tt_username_str == admin_username_from_config:
        is_main_tt_admin = True

    help_text = build_help_message(_, "teamtalk", is_telegram_admin=False, is_teamtalk_admin=is_main_tt_admin)
    # send_long_tt_reply might need connection.instance if it interacts with TT features beyond simple reply
    # For now, assuming tt_message.reply is sufficient.
    await send_long_tt_reply(tt_message.reply, help_text)


async def handle_tt_unknown_command(tt_message: TeamTalkMessage, _: callable, connection: TeamTalkConnection):
    """Handles unknown commands received from a TeamTalk user."""
    reply_text = _("Unknown command. Available commands: /sub, /unsub, /add_admin, /remove_admin, /help.")
    tt_message.reply(reply_text)
    logger.warning(
        "Received unknown TT command from %s on server %s: %s",
        ttstr(tt_message.user.username),
        connection.server_info.host if connection and connection.server_info else "Unknown",
        tt_message.content[:100],
    )
