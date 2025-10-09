"""Telegram bot command handlers for administrator actions."""

from gettext import NullTranslations
import logging
from typing import Annotated

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.command_bus.exceptions import NoHandlerFoundError
from bot.commands import GetOnlineUsersCommand, GetOnlineUsersResult
from bot.config import Settings
from bot.core.enums import AdminCommand
from bot.services.report_service import ReportService
from bot.services.schemas import UserDTO
from bot.telegram_bot.filters.admin import IsAdmin
from bot.telegram_bot.keyboards import create_user_selection_keyboard
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import (
    _show_banned_list_page,
    _show_subscriber_list_page,
)

logger = logging.getLogger(__name__)

admin_router = Router(name="admin_router")


async def show_user_buttons_from_list(
    message: Message,
    command_type: AdminCommand,
    translator: NullTranslations,
    users: list[UserDTO],
    server_host: str,
) -> None:
    """Creates and sends a keyboard with a list of users for moderation."""
    _ = translator.gettext

    if not users:
        await message.reply(
            _("No users found online on server {server_host}.").format(
                server_host=server_host
            )
        )
        return

    sorted_users = sorted(users, key=lambda u: u.nickname.lower())
    builder = await create_user_selection_keyboard(sorted_users, command_type)

    command_text_map = {
        AdminCommand.KICK: _("Select a user to kick from {server_host}:").format(
            server_host=server_host
        ),
        AdminCommand.BAN: _("Select a user to ban from {server_host}:").format(
            server_host=server_host
        ),
    }
    reply_text = command_text_map.get(command_type, _("Select a user:"))

    await message.reply(reply_text, reply_markup=builder.as_markup())


async def _handle_moderation_command(
    message: Message,
    command_type: AdminCommand,
    translator: NullTranslations,
    command_bus: CommandBus,
    settings: Settings,
) -> None:
    """Generic handler for moderation commands like kick and ban."""
    _ = translator.gettext
    try:
        result: GetOnlineUsersResult = await command_bus.execute(
            GetOnlineUsersCommand(
                is_caller_admin=True, lang_code=translator.info().get("language", "en")
            )
        )
    except NoHandlerFoundError:
        logger.critical("CRITICAL: No handler for GetOnlineUsersCommand!")
        await message.reply(_("This feature is temporarily unavailable."))
        return

    if result.success and result.users:
        await show_user_buttons_from_list(
            message,
            command_type,
            translator,
            result.users,
            settings.teamtalk.host_name,
        )
    else:
        await message.reply(result.error_message or _("Failed to get user list."))


@admin_router.message(Command("kick"), IsAdmin())
async def on_kick_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    command_bus: Annotated[CommandBus, FromDishka()],
    settings: Annotated[Settings, FromDishka()],
) -> None:
    """Handles the /kick command for administrators."""
    await _handle_moderation_command(
        message, AdminCommand.KICK, translator, command_bus, settings
    )


@admin_router.message(Command("ban"), IsAdmin())
async def on_ban_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    command_bus: Annotated[CommandBus, FromDishka()],
    settings: Annotated[Settings, FromDishka()],
) -> None:
    """Handles the /ban command for administrators."""
    await _handle_moderation_command(
        message, AdminCommand.BAN, translator, command_bus, settings
    )


@admin_router.message(Command("subscribers"), IsAdmin())
async def on_subscribers_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
) -> None:
    """Handles the /subscribers command for administrators."""
    await _show_subscriber_list_page(
        target=message,
        report_service=report_service,
        bot=bot,
        translator=translator,
        page=0,
    )


@admin_router.message(Command("unban"), IsAdmin())
async def on_unban_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
) -> None:
    """Handles the /unban command for administrators."""
    await _show_banned_list_page(
        target=message,
        report_service=report_service,
        bot=bot,
        translator=translator,
        page=0,
    )


@admin_router.message(Command("exit"), IsAdmin())
async def on_exit_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    dispatcher: Annotated[Dispatcher, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
) -> None:
    """Handles the /exit command to gracefully shut down the bot."""
    _ = translator.gettext
    await message.reply(_("Shutting down..."))
    await dispatcher.stop_polling()
    await bot.session.close()
