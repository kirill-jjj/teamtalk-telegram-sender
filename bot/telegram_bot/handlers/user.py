"""Telegram bot command handlers for regular user interactions."""

from gettext import NullTranslations
import logging
from typing import Annotated

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.command_bus.exceptions import NoHandlerFoundError
from bot.commands import GetOnlineUsersCommand, GetOnlineUsersResult
from bot.config import Settings
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.telegram_bot.api import safe_delete_message
from bot.telegram_bot.deeplink import handle_deeplink
from bot.telegram_bot.filters.subscription import IsSubscribed
from bot.telegram_bot.keyboards import (
    create_main_menu_keyboard,
    create_main_settings_keyboard,
)
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware
from bot.telegram_bot.types.bots import EventBot

logger = logging.getLogger(__name__)
user_commands_router = Router(name="user_commands_router")
user_commands_router.message.middleware(
    ActiveTeamTalkConnectionMiddleware(default_server_key=None)
)


@user_commands_router.message(CommandStart(deep_link=True, magic=F.args.as_("token")))
async def on_start_with_payload(
    message: Message,
    token: str,
    translator: Annotated[NullTranslations, FromDishka()],
    uow: Annotated[IUnitOfWork, FromDishka()],
    deeplink_service: Annotated[DeeplinkService, FromDishka()],
    settings: Annotated[Settings, FromDishka()],
) -> None:
    """Handle the /start command with a deeplink, using a magic filter."""
    if not message.from_user:
        return

    async with uow:
        user_settings = await uow.users.get_or_create(
            message.from_user.id,
            defaults={"language_code": settings.general.default_lang},
        )
        await handle_deeplink(
            message,
            token,
            translator,
            user_settings,
            uow=uow,
            deeplink_service=deeplink_service,
        )


@user_commands_router.message(CommandStart(deep_link=False))
async def on_start_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
) -> None:
    """Handles the /start command without a deeplink."""
    _ = translator.gettext
    await message.reply(_("Hello! Use /help to see available commands."))


@user_commands_router.message(Command("who"), IsSubscribed())
async def on_who_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    cache: Annotated[CacheService, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
    command_bus: Annotated[CommandBus, FromDishka()],
) -> None:
    """Handles the /who command by calling the user service to generate a report."""
    _ = translator.gettext
    if not message.from_user:
        return

    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        is_admin = cache.is_admin(message.from_user.id)
        command = GetOnlineUsersCommand(is_caller_admin=is_admin)
        try:
            result: GetOnlineUsersResult = await command_bus.execute(command)
        except NoHandlerFoundError:
            logger.critical("CRITICAL: No handler for GetOnlineUsersCommand!")
            await message.reply(_("This feature is temporarily unavailable."))
            return

        if not result.success:
            await message.reply(
                result.error_message or _("An error occurred.")
            )
            return

        if result.report_text:
            await message.reply(result.report_text)
        else:
            await message.reply(_("Failed to generate the report."))


def _build_telegram_help_message(
    translator: NullTranslations, *, is_admin: bool
) -> str:
    """Builds the help message for Telegram users."""
    _ = translator.gettext
    parts = [
        _("<b>Available Commands:</b>"),
        _(
            "/who - Show online users.\n"
            "/settings - Access the interactive settings menu "
            "(language, notifications, mute lists, NOON feature).\n"
            "/help - Show this help message.\n"
            "(Note: `/start` is used to initiate the bot and process deeplinks.)"
        ),
    ]
    if is_admin:
        parts.extend(
            [
                _("\n<b>Admin Commands:</b>"),
                _(
                    "/kick - Kick a user from the server (via buttons).\n"
                    "/ban - Ban a user from the server (via buttons).\n"
                    "/unban - Unban a user from the server "
                    "(shows a list of banned users).\n"
                    "/subscribers - View and manage subscribed users."
                ),
            ]
        )
    return "\n".join(parts)


@user_commands_router.message(Command("help"), IsSubscribed())
async def on_help_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    cache: Annotated[CacheService, FromDishka()],
) -> None:
    """Handles the /help command, showing available commands."""
    if not message.from_user:
        return

    is_admin = cache.is_admin(message.from_user.id)
    help_text = _build_telegram_help_message(translator, is_admin=is_admin)
    await message.reply(help_text, parse_mode="HTML")


@user_commands_router.message(Command("settings"), IsSubscribed())
async def on_settings_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
) -> None:
    """Handles the /settings command, showing the main settings menu."""
    _ = translator.gettext
    if not message.from_user:
        return

    await safe_delete_message(message, log_context_message="user settings command")
    settings_builder = await create_main_settings_keyboard(translator)
    try:
        await message.answer(
            text=_("Settings"), reply_markup=settings_builder.as_markup()
        )
    except TelegramAPIError:
        logger.exception("Could not send settings menu.")


@user_commands_router.message(Command("menu"), IsSubscribed())
async def on_menu_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    cache: Annotated[CacheService, FromDishka()],
) -> None:
    """Handles the /menu command, showing the main command menu."""
    _ = translator.gettext
    if not message.from_user:
        return

    await safe_delete_message(message, log_context_message="user menu command")
    is_admin = cache.is_admin(message.from_user.id)
    menu_builder = await create_main_menu_keyboard(translator, is_admin=is_admin)
    try:
        await message.answer(
            text=_("Main Menu:"), reply_markup=menu_builder.as_markup()
        )
    except TelegramAPIError:
        logger.exception("Could not send main menu.")
