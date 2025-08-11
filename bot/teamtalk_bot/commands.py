"""Command handlers for the TeamTalk bot interface."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING, Any, TypedDict

from dishka import FromDishka
from pydantic import BaseModel, Field, model_validator
import pytalk
from pytalk.message import Message as TeamTalkMessage

from bot.config import Settings
from bot.constants import (
    MSG_GENERAL_ERROR,
    TT_HELP_MESSAGE_PART_DELAY,
    TT_MAX_MESSAGE_BYTES,
)
from bot.core.enums import DeeplinkAction
from bot.core.exceptions import (
    MissingSettingsError,
    MissingTranslatorError,
)
from bot.database.repositories.admin_repository import AdminRepository
from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.database.repositories.user_repository import UserRepository
from bot.event_bus.bus import EventBus
from bot.models import Admin
from bot.services.cache_service import CacheService
from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.events import AdminStatusChangedEvent

if TYPE_CHECKING:
    from bot.teamtalk_bot.connection import TeamTalkConnection
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _split_text_for_tt(text: str, max_len_bytes: int) -> list[str]:
    """Splits a long text message into parts suitable for TeamTalk."""
    parts_to_send_list = []
    remaining_text = text

    while remaining_text:
        if len(remaining_text.encode("utf-8", errors="ignore")) <= max_len_bytes:
            parts_to_send_list.append(remaining_text)
            break

        current_chunk_str = ""
        current_chunk_bytes_len = 0
        last_safe_split_index_in_chunk = -1
        last_safe_split_index_in_remaining = -1

        for i, char_code in enumerate(remaining_text):
            char_bytes = char_code.encode("utf-8", errors="ignore")
            char_bytes_len = len(char_bytes)

            if current_chunk_bytes_len + char_bytes_len > max_len_bytes:
                if last_safe_split_index_in_chunk != -1:
                    parts_to_send_list.append(
                        current_chunk_str[:last_safe_split_index_in_chunk]
                    )
                    remaining_text = remaining_text[
                        last_safe_split_index_in_remaining:
                    ].lstrip()
                else:
                    parts_to_send_list.append(current_chunk_str)
                    remaining_text = remaining_text[i:].lstrip()
                break

            current_chunk_str += char_code
            current_chunk_bytes_len += char_bytes_len

            if char_code in ("\n", " "):
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1

            if i == len(remaining_text) - 1:
                parts_to_send_list.append(current_chunk_str)
                remaining_text = ""
                break
        else:
            if current_chunk_str and not remaining_text:
                pass
            remaining_text = ""
    return parts_to_send_list


async def _send_long_tt_reply(
    reply_method: Callable[[str], None],
    text: str,
    max_len_bytes: int = TT_MAX_MESSAGE_BYTES,
) -> None:
    """Splits a long text message into parts suitable for TeamTalk and sends them."""
    if not text:
        return

    parts_to_send_list = await asyncio.to_thread(
        _split_text_for_tt, text, max_len_bytes
    )

    for part_idx, part_to_send_str in enumerate(parts_to_send_list):
        if part_to_send_str.strip():
            try:
                reply_method(part_to_send_str)
                encoded_len = len(part_to_send_str.encode("utf-8", errors="ignore"))
                logger.debug(
                    "Sent part %s/%s of TT message, length %s bytes.",
                    part_idx + 1,
                    len(parts_to_send_list),
                    encoded_len,
                )
                if part_idx < len(parts_to_send_list) - 1:
                    await asyncio.sleep(TT_HELP_MESSAGE_PART_DELAY)
            except pytalk.exceptions.TeamTalkException:
                logger.exception("Error sending part %s of TT message.", part_idx + 1)
                break


def _handle_command_errors(
    *, reply_to_user_on_error: bool = True
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[None]]]:
    """Decorator to handle common exceptions for TeamTalk command handlers."""

    def decorator(
        func: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[None]]:
        @functools.wraps(func)
        async def wrapper(
            tt_message: TeamTalkMessage,
            *args: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> None:
            try:
                await func(tt_message, *args, **kwargs)
            except (
                TelegramAPIError,
                SQLAlchemyError,
                pytalk.exceptions.TeamTalkException,
            ):
                translator = kwargs.get("translator")
                _ = (
                    translator.gettext
                    if isinstance(translator, NullTranslations)
                    else lambda s: s
                )

                logger.exception(
                    "Error in TeamTalk command '%s' for user %s.",
                    func.__name__,
                    ttstr(tt_message.user.username)
                    if tt_message and tt_message.user
                    else "Unknown TT User",
                )
                if reply_to_user_on_error:
                    try:
                        error_msg_for_user = _(MSG_GENERAL_ERROR)
                        tt_message.reply(error_msg_for_user)
                    except Exception:
                        logger.exception(
                            "Failed to send error reply to TT user %s "
                            "after command '%s' failed.",
                            ttstr(tt_message.user.username)
                            if tt_message and tt_message.user
                            else "Unknown TT User",
                            func.__name__,
                        )

        return wrapper

    return decorator


class AdminIdArgs(BaseModel):
    """Parses and validates arguments for admin commands that take Telegram IDs."""

    valid_ids: list[int] = Field(default_factory=list)
    invalid_entries: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def parse_str_to_dict(cls, data: str | None) -> dict[str, list[int] | list[str]]:
        """Parse a string of space-separated args into valid IDs and invalid entries."""
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


def is_tt_admin(func: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
    """Decorator to check if a TeamTalk user is the configured main admin."""

    @functools.wraps(func)
    async def wrapper(
        tt_message: TeamTalkMessage,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        settings = kwargs.get("settings")
        if not isinstance(settings, Settings):
            raise MissingSettingsError
        translator = kwargs.get("translator")
        if not isinstance(translator, NullTranslations):
            raise MissingTranslatorError
        _ = translator.gettext
        if (
            not settings.general.admin_username
            or ttstr(tt_message.user.username) != settings.general.admin_username
        ):
            logger.warning(
                "Unauthorized admin command by TT user %s for %s.",
                ttstr(tt_message.user.username),
                func.__name__,
            )
            tt_message.reply(_("You are not authorized to perform this action."))
            return
        await func(tt_message, *args, **kwargs)

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
    errors = [
        _(error_msg_source).format(telegram_id=failed_id) for failed_id in failed_ids
    ]
    errors.extend(
        [
            _(invalid_id_msg_source).format(telegram_id_str=invalid_entry)
            for invalid_entry in invalid_entries
        ]
    )
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


class DeeplinkConfig(TypedDict):
    """Configuration for a deeplink action."""

    get_payload: Callable[[TeamTalkMessage], str | None]
    reply_text_key: str


async def _manage_admin_ids(
    tt_message: TeamTalkMessage,
    args_str: str | None,
    translator: NullTranslations,
    repo_action: Callable[[Any], Awaitable[Any]],
    *,
    is_add_action: bool,
    prompt_msg_key: str,
    error_msg_key: str,
    invalid_id_msg_key: str,
    header_msg_key: str,
    settings: Settings,
    cache: CacheService,
    event_bus: EventBus,
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
            admin = await admin_repo.get_by_id(telegram_id)
            if (is_add_action and not admin) or (not is_add_action and admin):
                if is_add_action:
                    await repo_action(Admin(telegram_id=telegram_id))
                else:
                    await repo_action(admin)

            if is_add_action:
                cache.add_admin(telegram_id)
            else:
                cache.remove_admin(telegram_id)

            user_settings = await user_repo.get_or_create(
                telegram_id, {"language_code": settings.general.default_lang}
            )
            await event_bus.publish(
                AdminStatusChangedEvent(
                    telegram_id=telegram_id,
                    is_admin=is_add_action,
                    lang_code=user_settings.language_code,
                )
            )
            success_count += 1
        except Exception:
            failed_action_ids.append(telegram_id)
            action_str = "add" if is_add_action else "remove"
            logger.exception("Failed to %s admin %s", action_str, telegram_id)

    if is_add_action:
        s_msg = "Successfully added {count} admin."
        p_msg = "Successfully added {count} admins."
    else:
        s_msg = "Successfully removed {count} admin."
        p_msg = "Successfully removed {count} admins."

    success_message = translator.ngettext(s_msg, p_msg, success_count).format(
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


@_handle_command_errors()
async def reply_with_deeplink(
    tt_message: TeamTalkMessage,
    deeplink_repo: DeeplinkRepository,
    translator: NullTranslations,
    action: DeeplinkAction,
    reply_text_source: str,
    settings: Settings,
    cache: CacheService,
    payload: str | None = None,
) -> None:
    """Generates a deeplink and replies to the user with it."""
    _ = translator.gettext
    deeplink = await deeplink_repo.create(
        action,
        settings.operational_parameters.deeplink_ttl_seconds,
        payload=payload,
    )
    bot_username = cache.get_bot_username()
    if not bot_username:
        logger.error("Bot username not found in cache. Cannot create deeplink.")
        tt_message.reply(
            _("Could not generate a link, bot username is not configured.")
        )
        return
    deeplink_url = f"https://t.me/{bot_username}?start={deeplink.token}"
    logger.info(
        "Generated deeplink %s for TT user %s",
        deeplink.token,
        ttstr(tt_message.user.username),
    )
    tt_message.reply(_(reply_text_source).format(deeplink_url=deeplink_url))


DEEPLINK_CONFIG: dict[DeeplinkAction, DeeplinkConfig] = {
    DeeplinkAction.SUBSCRIBE: {
        "get_payload": lambda msg: ttstr(msg.user.username),
        "reply_text_key": (
            "Click this link to subscribe to notifications "
            "(link valid for 5 minutes):\n{deeplink_url}"
        ),
    },
    DeeplinkAction.UNSUBSCRIBE: {
        "get_payload": lambda _: None,
        "reply_text_key": (
            "Click this link to unsubscribe from notifications "
            "(link valid for 5 minutes):\n{deeplink_url}"
        ),
    },
}


async def _handle_deeplink_command(
    tt_message: TeamTalkMessage,
    deeplink_repo: DeeplinkRepository,
    translator: NullTranslations,
    settings: Settings,
    cache: CacheService,
    action: DeeplinkAction,
) -> None:
    """Generic handler for subscribe/unsubscribe commands."""
    _ = translator.gettext
    config = DEEPLINK_CONFIG[action]
    payload = config["get_payload"](tt_message)
    reply_text_source = _(config["reply_text_key"])

    await reply_with_deeplink(
        tt_message=tt_message,
        deeplink_repo=deeplink_repo,
        translator=translator,
        action=action,
        payload=payload,
        reply_text_source=reply_text_source,
        settings=settings,
        cache=cache,
    )


async def on_subscribe(
    tt_message: TeamTalkMessage,
    deeplink_repo: FromDishka[DeeplinkRepository],
    translator: NullTranslations,
    settings: FromDishka[Settings],
    cache: FromDishka[CacheService],
) -> None:
    """Handles the /sub command from a TeamTalk user."""
    await _handle_deeplink_command(
        tt_message, deeplink_repo, translator, settings, cache, DeeplinkAction.SUBSCRIBE
    )


async def on_unsubscribe(
    tt_message: TeamTalkMessage,
    deeplink_repo: FromDishka[DeeplinkRepository],
    translator: NullTranslations,
    settings: FromDishka[Settings],
    cache: FromDishka[CacheService],
) -> None:
    """Handles the /unsub command from a TeamTalk user."""
    await _handle_deeplink_command(
        tt_message,
        deeplink_repo,
        translator,
        settings,
        cache,
        DeeplinkAction.UNSUBSCRIBE,
    )


@is_tt_admin
async def on_add_admin(
    tt_message: TeamTalkMessage,
    translator: NullTranslations,
    settings: FromDishka[Settings],
    cache: FromDishka[CacheService],
    event_bus: FromDishka[EventBus],
    admin_repo: FromDishka[AdminRepository],
    user_repo: FromDishka[UserRepository],
    *,
    args_str: str | None,
) -> None:
    """Handles the /add_admin command from a TeamTalk admin."""
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message,
        args_str=args_str,
        translator=translator,
        repo_action=admin_repo.add,
        is_add_action=True,
        prompt_msg_key=_("Please provide Telegram IDs. Example: {cmd} 12345678").format(
            cmd=tt_cmds.TT_CMD_ADD_ADMIN
        ),
        error_msg_key=_("ID {telegram_id} is already an admin or failed to add."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric ID."),
        header_msg_key=_("Action Results:"),
        settings=settings,
        cache=cache,
        event_bus=event_bus,
        admin_repo=admin_repo,
        user_repo=user_repo,
    )


@is_tt_admin
async def on_remove_admin(
    tt_message: TeamTalkMessage,
    translator: NullTranslations,
    settings: FromDishka[Settings],
    cache: FromDishka[CacheService],
    event_bus: FromDishka[EventBus],
    admin_repo: FromDishka[AdminRepository],
    user_repo: FromDishka[UserRepository],
    *,
    args_str: str | None,
) -> None:
    """Handles the /remove_admin command from a TeamTalk admin."""
    _ = translator.gettext
    await _manage_admin_ids(
        tt_message=tt_message,
        args_str=args_str,
        translator=translator,
        repo_action=admin_repo.delete,
        is_add_action=False,
        prompt_msg_key=_("Please provide Telegram IDs. Example: {cmd} 12345678").format(
            cmd=tt_cmds.TT_CMD_REMOVE_ADMIN
        ),
        error_msg_key=_("Admin with ID {telegram_id} not found or failed to remove."),
        invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric ID."),
        header_msg_key=_("Action Results:"),
        settings=settings,
        cache=cache,
        event_bus=event_bus,
        admin_repo=admin_repo,
        user_repo=user_repo,
    )


def _build_teamtalk_help_message(
    translator: NullTranslations, *, is_admin: bool
) -> str:
    """Builds the help message for TeamTalk users."""
    _ = translator.gettext
    parts = [
        _("Available commands:"),
        _(
            "/sub - Get a link to subscribe to notifications.\n"
            "/unsub - Get a link to unsubscribe from notifications.\n"
            "/help - Show help."
        ),
    ]
    if is_admin:
        parts.extend(
            [
                _("\nAdmin commands (MAIN_ADMIN from config only):"),
                _(
                    "/add_admin <Telegram ID> [<Telegram ID>...] - Add bot admin.\n"
                    "/remove_admin <Telegram ID> [<Telegram ID>...] - Remove bot admin."
                ),
            ]
        )
    return "\n".join(parts)


async def on_help(
    tt_message: TeamTalkMessage,
    translator: NullTranslations,
    settings: Settings,
    **_kwargs: Any,  # noqa: ANN401
) -> None:
    """Handles the /help command from a TeamTalk user."""
    tt_username_str = ttstr(tt_message.user.username)
    is_main_tt_admin = bool(
        settings.general.admin_username
        and tt_username_str == settings.general.admin_username
    )
    help_text = _build_teamtalk_help_message(translator, is_admin=is_main_tt_admin)
    await _send_long_tt_reply(tt_message.reply, help_text)


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
    reply_text = _("Unknown command. Available commands: {commands}.").format(
        commands=available_commands
    )
    tt_message.reply(reply_text)
    logger.warning(
        "Unknown TT command from %s on %s: %s",
        ttstr(tt_message.user.username),
        connection.server_info.host,
        tt_message.content[:100],
    )
