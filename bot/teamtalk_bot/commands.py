"""Command handlers for the TeamTalk bot interface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING, Any, TypedDict

from aiogram import Bot
from pydantic import BaseModel, Field, model_validator
import pytalk
from pytalk.message import Message as TeamTalkMessage

from bot.config import Settings
from bot.core.enums import DeeplinkAction
from bot.core.exceptions import (
    MissingSettingsError,
    MissingTranslatorError,
)
from bot.core.utils import build_help_message
from bot.database.repositories.admin_repository import AdminRepository
from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.database.repositories.user_repository import UserRepository
from bot.models import Admin
from bot.services.cache_service import CacheService
from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.utils import handle_command_errors, send_long_tt_reply
from bot.telegram_bot.utils import update_user_bot_commands

if TYPE_CHECKING:
    from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


class AdminIdArgs(BaseModel):
    """Parses and validates arguments for admin commands that take Telegram IDs."""

    valid_ids: list[int] = Field(default_factory=list)
    invalid_entries: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def parse_str_to_dict(cls, data: str | None) -> dict[str, list[int] | list[str]]:
        """Parses a string of space-separated arguments into valid IDs and invalid entries."""
        if not isinstance(data, str) or not (command_args_str := data.strip()):
            return {"valid_ids": [], "invalid_entries": []}
        valid_ids = []
        invalid_entries = []
        for part in command_args_str.split():
            if part.isdigit():
                valid_ids.append(int(part))
            else:
                invalid_entries.append(part)
        return {"valid_ids": valid_ids, "invalid_entries": invalid_entries}


def is_tt_admin(func: Callable[..., Any]) -> Callable[..., Any | None]:
    """Decorator to check if a TeamTalk user is the configured main admin."""

    @functools.wraps(func)
    async def wrapper(tt_message: TeamTalkMessage, *args: Any, **kwargs: Any) -> Any | None:
        settings = kwargs.get("settings")
        if not isinstance(settings, Settings):
            raise MissingSettingsError
        translator = kwargs.get("translator")
        if not isinstance(translator, NullTranslations):
            raise MissingTranslatorError
        _ = translator.gettext
        if not settings.general.admin_username or ttstr(tt_message.user.username) != settings.general.admin_username:
            logger.warning(
                "Unauthorized admin command by TT user %s for %s.",
                ttstr(tt_message.user.username),
                func.__name__,
            )
            tt_message.reply(_("You are not authorized to perform this action."))
            return None
        return await func(tt_message, *args, **kwargs)

    return wrapper


def _create_admin_action_report(
    translator: NullTranslations,
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
    errors = [_(error_msg_source).format(telegram_id=failed_id) for failed_id in failed_ids]
    errors.extend([_(invalid_id_msg_source).format(telegram_id_str=invalid_entry) for invalid_entry in invalid_entries])
    if errors:
        header = _(header_source)
        error_list_str = "\n".join(f"- {error}" for error in errors)
        reply_parts.append(f"{header}\n{error_list_str}")
    if not reply_parts:
        return str(_("No action was performed. Please check the IDs provided."))
    return "\n\n".join(reply_parts)


class AdminActionConfig(TypedDict):
    """Configuration for a specific admin action."""

    service_func: Callable[..., Awaitable[bool]]
    success_msg: tuple[str, str]


async def _manage_admin_ids(
    tt_message: TeamTalkMessage,
    args_str: str | None,
    translator: NullTranslations,
    action_type: str,
    prompt_msg_key: str,
    error_msg_key: str,
    invalid_id_msg_key: str,
    header_msg_key: str,
    settings: Settings,
    cache: CacheService,
    bot: Bot,
    admin_repo: AdminRepository,
    user_repo: UserRepository,
) -> None:
    _ = translator.gettext
    args = AdminIdArgs.model_validate(args_str)
    if not args.valid_ids and not args.invalid_entries:
        tt_message.reply(_(prompt_msg_key))
        return

    success_count = 0
    failed_action_ids = []

    for telegram_id in args.valid_ids:
        try:
            if action_type == "add":
                admin = await admin_repo.get_by_id(telegram_id)
                if not admin:
                    await admin_repo.add(Admin(telegram_id=telegram_id))
            elif action_type == "remove":
                admin = await admin_repo.get_by_id(telegram_id)
                if admin:
                    await admin_repo.delete(admin)

            cache.add_admin(telegram_id) if action_type == "add" else cache.remove_admin(telegram_id)
            user_settings = await user_repo.get_or_create(telegram_id, {"language_code": settings.general.default_lang})
            await update_user_bot_commands(telegram_id, user_settings.language_code, cache, bot, translator)
            success_count += 1
        except Exception:
            failed_action_ids.append(telegram_id)
            logger.exception("Failed to %s admin %s", action_type, telegram_id)

    success_msg_single, success_msg_plural = (
        ("Successfully added {count} admin.", "Successfully added {count} admins.")
        if action_type == "add"
        else (
            "Successfully removed {count} admin.",
            "Successfully removed {count} admins.",
        )
    )
    success_message = translator.ngettext(success_msg_single, success_msg_plural, success_count).format(
        count=success_count
    )

    report = _create_admin_action_report(
        translator,
        success_count,
        failed_action_ids,
        args.invalid_entries,
        success_message,
        error_msg_key,
        invalid_id_msg_key,
        header_msg_key,
    )
    tt_message.reply(report)


@handle_command_errors()
async def reply_with_deeplink(
    tt_message: TeamTalkMessage,
    deeplink_repo: DeeplinkRepository,
    translator: NullTranslations,
    action: DeeplinkAction,
    success_log_message: str,
    reply_text_source: str,
    settings: Settings,
    bot: Bot,
    payload: str | None = None,
) -> None:
    """Generates a deeplink and replies to the user with it."""
    _ = translator.gettext
    deeplink = await deeplink_repo.create(
        action,
        settings.operational_parameters.deeplink_ttl_seconds,
        payload=payload,
    )
    bot_info = await bot.get_me()
    deeplink_url = f"https://t.me/{bot_info.username}?start={deeplink.token}"
    logger.info(
        "Generated deeplink %s for TT user %s",
        deeplink.token,
        ttstr(tt_message.user.username),
    )
    tt_message.reply(_(reply_text_source).format(deeplink_url=deeplink_url))


async def on_subscribe(
    tt_message: TeamTalkMessage,
    deeplink_repo: DeeplinkRepository,
    translator: NullTranslations,
    settings: Settings,
    bot: Bot,
) -> None:
    """Handles the /sub command from a TeamTalk user."""
    _ = translator.gettext
    await reply_with_deeplink(
        tt_message=tt_message,
        deeplink_repo=deeplink_repo,
        translator=translator,
        action=DeeplinkAction.SUBSCRIBE,
        payload=ttstr(tt_message.user.username),
        success_log_message="Generated subscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_(
            "Click this link to subscribe to notifications (link valid for 5 minutes):\n{deeplink_url}"
        ),
        settings=settings,
        bot=bot,
    )


async def on_unsubscribe(
    tt_message: TeamTalkMessage,
    deeplink_repo: DeeplinkRepository,
    translator: NullTranslations,
    settings: Settings,
    bot: Bot,
) -> None:
    """Handles the /unsub command from a TeamTalk user."""
    _ = translator.gettext
    await reply_with_deeplink(
        tt_message=tt_message,
        deeplink_repo=deeplink_repo,
        translator=translator,
        action=DeeplinkAction.UNSUBSCRIBE,
        payload=None,
        success_log_message="Generated unsubscribe deeplink {token} for TT user {sender_username}",
        reply_text_source=_(
            "Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_url}"
        ),
        settings=settings,
        bot=bot,
    )


@is_tt_admin
async def on_add_admin(
    tt_message: TeamTalkMessage,
    translator: NullTranslations,
    settings: Settings,
    cache: CacheService,
    bot: Bot,
    admin_repo: AdminRepository,
    user_repo: UserRepository,
    *,
    args_str: str | None,
) -> None:
    """Handles the /add_admin command from a TeamTalk admin."""
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message,
        args_str=args_str,
        translator=translator,
        action_type="add",
        prompt_msg_key=_("Please provide Telegram IDs. Example: {cmd} 12345678").format(cmd=tt_cmds.TT_CMD_ADD_ADMIN),
        error_msg_key=_("ID {telegram_id} is already an admin or failed to add."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric ID."),
        header_msg_key=_("Action Results:"),
        settings=settings,
        cache=cache,
        bot=bot,
        admin_repo=admin_repo,
        user_repo=user_repo,
    )


@is_tt_admin
async def on_remove_admin(
    tt_message: TeamTalkMessage,
    translator: NullTranslations,
    settings: Settings,
    cache: CacheService,
    bot: Bot,
    admin_repo: AdminRepository,
    user_repo: UserRepository,
    *,
    args_str: str | None,
) -> None:
    """Handles the /remove_admin command from a TeamTalk admin."""
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message,
        args_str=args_str,
        translator=translator,
        action_type="remove",
        prompt_msg_key=_("Please provide Telegram IDs. Example: {cmd} 12345678").format(
            cmd=tt_cmds.TT_CMD_REMOVE_ADMIN
        ),
        error_msg_key=_("Admin with ID {telegram_id} not found or failed to remove."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric ID."),
        header_msg_key=_("Action Results:"),
        settings=settings,
        cache=cache,
        bot=bot,
        admin_repo=admin_repo,
        user_repo=user_repo,
    )


async def on_help(
    tt_message: TeamTalkMessage,
    translator: NullTranslations,
    settings: Settings,
    **_kwargs: Any,
) -> None:
    """Handles the /help command from a TeamTalk user."""
    tt_username_str = ttstr(tt_message.user.username)
    is_main_tt_admin = bool(settings.general.admin_username and tt_username_str == settings.general.admin_username)
    help_text = build_help_message(
        translator,
        "teamtalk",
        is_telegram_admin=False,
        is_teamtalk_admin=is_main_tt_admin,
    )
    await send_long_tt_reply(tt_message.reply, help_text)


async def on_unknown(
    tt_message: TeamTalkMessage,
    translator: NullTranslations,
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
        "Unknown TT command from %s on %s: %s",
        ttstr(tt_message.user.username),
        connection.server_info.host,
        tt_message.content[:100],
    )
