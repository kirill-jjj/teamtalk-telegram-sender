"""Command handlers for the TeamTalk bot interface."""

from __future__ import annotations

from collections.abc import Callable
import functools
import gettext
import logging
from typing import TYPE_CHECKING, Any  # Ensure Any is imported

from aiogram.exceptions import TelegramAPIError
from pydantic import BaseModel, Field, model_validator
import pytalk
from pytalk.exceptions import TeamTalkException
from pytalk.message import Message as TeamTalkMessage
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession  # Changed to SQLModel's AsyncSession

from bot.core.enums import DeeplinkAction
from bot.core.utils import build_help_message
from bot.database.crud import create_deeplink
from bot.services import admin_service
from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.utils import send_long_tt_reply

if TYPE_CHECKING:
    from bot.services_container import Services
    from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


class AdminIdArgs(BaseModel):
    """Parses and validates arguments for admin commands that take Telegram IDs."""

    valid_ids: list[int] = Field(default_factory=list)
    invalid_entries: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def parse_str_to_dict(cls, data: str | None) -> dict[str, list[int] | list[str]]:  # More specific type
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


def is_tt_admin(func: Callable[..., Any]) -> Callable[..., Any | None]:
    """Decorator to check if a TeamTalk user is the configured main admin."""

    @functools.wraps(func)
    async def wrapper(tt_message: TeamTalkMessage, *args: Any, **kwargs: Any) -> Any | None:  # noqa: ANN401
        services_from_kwargs = kwargs.get("services")
        # Check type by name to avoid circular import issues with Services
        if not hasattr(services_from_kwargs, "__class__") or services_from_kwargs.__class__.__name__ != "Services":
            # This check ensures services_from_kwargs is indeed a Services instance or raises error
            # Define the error message as a constant or a local variable
            error_msg = "Services not found or of incorrect type in kwargs for is_tt_admin."
            raise TypeError(error_msg)
        services: Services = services_from_kwargs  # type: ignore[assignment] # Trusting the dynamic check

        translator = kwargs.get("translator")
        if not translator or not isinstance(translator, gettext.GNUTranslations):
            raise TypeError("Translator not in kwargs.")  # noqa: TRY003
        _ = translator.gettext

        username = ttstr(tt_message.user.username)
        admin_username = services.config.general.admin_username

        if not admin_username or username != admin_username:
            logger.warning("Unauthorized admin command attempt by TT user %s for function %s.", username, func.__name__)
            tt_message.reply(_("You are not authorized to perform this action."))
            return None
        return await func(tt_message, *args, **kwargs)

    return wrapper


# Removed _execute_admin_action_for_id as its logic is now in admin_service


def _create_admin_action_report(
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
    action_type: str,  # "add" or "remove"
    prompt_msg_key: str,
    error_msg_key: str,
    invalid_id_msg_key: str,
    header_msg_key: str,
    services: Services,
) -> None:
    _ = translator.gettext
    args = AdminIdArgs.model_validate(args_str)
    if not args.valid_ids and not args.invalid_entries:
        tt_message.reply(_(prompt_msg_key))
        return

    success_count = 0
    failed_action_ids = []
    for telegram_id in args.valid_ids:
        user_settings = await services.get_or_create_user_settings(telegram_id, session)
        # Ensure user_settings has a default language if new
        if not user_settings.language_code:
            user_settings.language_code = services.config.general.default_lang
            # No need to save here just for this, admin_service will use it

        action_successful = False
        if action_type == "add":
            logger.info(
                "Attempting to add admin for TG ID %s by TT admin %s.", telegram_id, ttstr(tt_message.user.username)
            )
            action_successful = await admin_service.add_admin_full(session, telegram_id, user_settings, services)
        elif action_type == "remove":
            logger.info(
                "Attempting to remove admin for TG ID %s by TT admin %s.", telegram_id, ttstr(tt_message.user.username)
            )
            action_successful = await admin_service.remove_admin_full(session, telegram_id, user_settings, services)

        if action_successful:
            success_count += 1
            logger.info(
                "Successfully processed %s admin for TG ID %s (DB, cache, commands updated via admin_service).",
                action_type,
                telegram_id,
            )
        else:
            failed_action_ids.append(telegram_id)
            logger.warning(
                "Failed to process %s admin for TG ID %s (e.g., already in state or service error).",
                action_type,
                telegram_id,
            )

    success_message_formatted = ""
    if action_type == "add":
        success_message_formatted = translator.ngettext(
            "Successfully added {count} admin.", "Successfully added {count} admins.", success_count
        ).format(count=success_count)
    elif action_type == "remove":
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
    translator: gettext.GNUTranslations,
    action: DeeplinkAction,
    success_log_message: str,
    reply_text_source: str,
    _error_reply_source: str,  # Not directly used, but kept for signature consistency if refactoring
    services: Services,
    payload: str | None = None,
) -> None:
    _ = translator.gettext
    sender_tt_username = ttstr(tt_message.user.username)
    try:
        token = await create_deeplink(
            session,
            action,
            services.config.operational_parameters.deeplink_ttl_seconds,
            payload=payload,
            expected_telegram_id=None,
        )
        bot_info = await services.bot_event.get_me()
        deeplink_url = f"https://t.me/{bot_info.username}?start={token}"
        logger.info("%s Token: %s, User: %s", success_log_message, token, sender_tt_username)
        if "{deeplink_url}" in reply_text_source:
            reply_text = _(reply_text_source).format(deeplink_url=deeplink_url)
        else:
            reply_text = _(reply_text_source)
        tt_message.reply(reply_text)
    except TelegramAPIError:
        logger.exception(
            "Telegram API error processing deeplink action %s for TT user %s.",
            action,
            sender_tt_username,
        )
        try:
            tt_message.reply(_("An error occurred. Please try again later."))
        except Exception:
            logger.exception("Failed to send Telegram API error reply to TT user %s.", sender_tt_username)
    except SQLAlchemyError:
        logger.exception(
            "Database error creating deeplink for action %s for TT user %s.",
            action,
            sender_tt_username,
        )
        try:
            tt_message.reply(_("An error occurred. Please try again later."))
        except Exception:
            logger.exception("Failed to send DB error reply to TT user %s.", sender_tt_username)
    except TeamTalkException:
        logger.exception(
            "TeamTalk error processing deeplink action %s for TT user %s.",
            action,
            sender_tt_username,
        )
        try:
            tt_message.reply(_("An error occurred. Please try again later."))
        except Exception:
            logger.exception("Failed to send TT error reply to TT user %s.", sender_tt_username)


async def handle_tt_subscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: Services,
    _connection: TeamTalkConnection,  # Marked as unused
) -> None:
    """Handles the /sub command from a TeamTalk user.

    Generates a subscription deeplink and replies to the user.
    """
    _ = translator.gettext
    sender_tt_username = ttstr(tt_message.user.username)
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        translator=translator,
        action=DeeplinkAction.SUBSCRIBE,
        payload=sender_tt_username,
        success_log_message="Generated subscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_(
            "Click this link to subscribe to notifications (link valid for 5 minutes):\n{deeplink_url}"
        ),
        _error_reply_source=_("An error occurred processing your request. Please try again later."),
        services=services,
    )


async def handle_tt_unsubscribe_command(
    tt_message: TeamTalkMessage,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: Services,
    _connection: TeamTalkConnection,  # Marked as unused
) -> None:
    """Handles the /unsub command from a TeamTalk user.

    Generates an unsubscription deeplink and replies to the user.
    """
    _ = translator.gettext
    await _generate_and_reply_deeplink(
        tt_message=tt_message,
        session=session,
        translator=translator,
        action=DeeplinkAction.UNSUBSCRIBE,
        payload=None,
        success_log_message="Generated unsubscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_(
            "Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_url}"
        ),
        _error_reply_source=_("An error occurred processing your request. Please try again later."),
        services=services,
    )


@is_tt_admin
async def handle_tt_add_admin_command(
    tt_message: TeamTalkMessage,
    translator: gettext.GNUTranslations,
    session: AsyncSession,
    services: Services,  # will be in kwargs for decorator
    _connection: TeamTalkConnection,  # Marked as unused
    *,
    args_str: str | None,
) -> None:
    """Handles the /add_admin command from a TeamTalk admin.

    Adds specified Telegram IDs as bot administrators.
    """
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message,
        args_str=args_str,
        session=session,
        translator=translator,
        action_type="add",
        prompt_msg_key=_(
            "Please provide Telegram IDs after the command. Example: {add_admin_cmd} 12345678 98765432"
        ).format(add_admin_cmd=tt_cmds.TT_CMD_ADD_ADMIN),
        error_msg_key=_(
            "ID {telegram_id} is already an admin or failed to add."
        ),  # This message might need adjustment as service layer handles "already admin"
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric Telegram ID."),
        header_msg_key=_("Action Results:"),
        services=services,
    )


@is_tt_admin
async def handle_tt_remove_admin_command(
    tt_message: TeamTalkMessage,
    translator: gettext.GNUTranslations,
    session: AsyncSession,
    services: Services,
    _connection: TeamTalkConnection,  # Marked as unused
    *,
    args_str: str | None,
) -> None:
    """Handles the /remove_admin command from a TeamTalk admin.

    Removes bot administrator privileges from specified Telegram IDs.
    """
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message,
        args_str=args_str,
        session=session,
        translator=translator,
        action_type="remove",
        prompt_msg_key=_(
            "Please provide Telegram IDs after the command. Example: {remove_admin_cmd} 12345678 98765432"
        ).format(remove_admin_cmd=tt_cmds.TT_CMD_REMOVE_ADMIN),
        error_msg_key=_(
            "Admin with ID {telegram_id} not found or failed to remove."
        ),  # This message might need adjustment
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric Telegram ID."),
        header_msg_key=_("Action Results:"),
        services=services,
    )


async def handle_tt_help_command(  # Added return type hint
    tt_message: TeamTalkMessage,
    translator: gettext.GNUTranslations,
    services: Services,
    _connection: TeamTalkConnection,  # Marked as unused
) -> None:
    """Handles the /help command from a TeamTalk user.

    Sends a help message tailored to longed to the user's admin status.
    """
    _ = translator.gettext
    is_main_tt_admin = False
    tt_username_str = None
    if tt_message.user and hasattr(tt_message.user, "username"):
        tt_username_str = ttstr(tt_message.user.username)
    admin_username_from_config = services.config.general.admin_username

    if tt_username_str and admin_username_from_config and tt_username_str == admin_username_from_config:
        is_main_tt_admin = True

    help_text = build_help_message(translator, "teamtalk", is_telegram_admin=False, is_teamtalk_admin=is_main_tt_admin)
    # send_long_tt_reply might need connection.instance if it interacts with TT features beyond simple reply
    # For now, assuming tt_message.reply is sufficient.
    await send_long_tt_reply(tt_message.reply, help_text)


async def handle_tt_unknown_command(  # Added return type hint
    tt_message: TeamTalkMessage,
    translator: gettext.GNUTranslations | gettext.NullTranslations,
    connection: TeamTalkConnection,
) -> None:
    """Handles unknown commands received from a TeamTalk user."""
    _ = translator.gettext
    available_commands = ", ".join(
        [
            tt_cmds.TT_CMD_SUBSCRIBE,
            tt_cmds.TT_CMD_UNSUBSCRIBE,
            tt_cmds.TT_CMD_ADD_ADMIN,
            tt_cmds.TT_CMD_REMOVE_ADMIN,
            tt_cmds.TT_CMD_HELP,
        ]
    )
    reply_text = _("Unknown command. Available commands: {commands}.").format(commands=available_commands)
    tt_message.reply(reply_text)
    logger.warning(
        "Received unknown TT command from %s on server %s: %s",
        ttstr(tt_message.user.username),
        connection.server_info.host if connection and connection.server_info else "Unknown",
        tt_message.content[:100],
    )
