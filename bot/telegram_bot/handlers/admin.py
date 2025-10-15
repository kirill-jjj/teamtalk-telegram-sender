"""Telegram bot command handlers for administrator actions."""

from gettext import NullTranslations
import logging
from typing import Annotated

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.config import Settings
from bot.core.enums import AdminCommand
from bot.services.cache_service import CacheService
from bot.services.report_service import ReportService
from bot.services.schemas import UserDTO
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.filters.admin import IsAdmin
from bot.telegram_bot.formatters import format_moderation_prompt
from bot.telegram_bot.keyboards import (
    create_banned_user_list_keyboard,
    create_subscriber_list_keyboard,
    create_user_selection_keyboard,
)
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import display_paginated_list

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

    builder = await create_user_selection_keyboard(users, command_type)

    reply_text = format_moderation_prompt(command_type, server_host, translator)

    await message.reply(reply_text, reply_markup=builder.as_markup())


async def show_moderation_user_list(
    message: Message,
    command_type: AdminCommand,
    translator: NullTranslations,
    command_bus: CommandBus,
    settings: Settings,
    report_service: ReportService,
    cache_service: CacheService,
    user_settings_service: UserSettingsService,
) -> None:
    """Generic handler for moderation commands like kick and ban."""
    _ = translator.gettext
    if not message.from_user:
        return

    (
        sorted_users,
        error_message,
    ) = await report_service.get_sorted_online_users_for_moderation(
        telegram_user_id=message.from_user.id,
        translator=translator,
        cache_service=cache_service,
        user_settings_service=user_settings_service,
        command_bus=command_bus,
    )

    if sorted_users:
        await show_user_buttons_from_list(
            message,
            command_type,
            translator,
            sorted_users,
            settings.teamtalk.host_name,
        )
    else:
        await message.reply(error_message or _("Failed to get user list."))


@admin_router.message(Command("kick"), IsAdmin())
async def on_kick_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    command_bus: Annotated[CommandBus, FromDishka()],
    settings: Annotated[Settings, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
    cache_service: Annotated[CacheService, FromDishka()],
    user_settings_service: Annotated[UserSettingsService, FromDishka()],
) -> None:
    """Handles the /kick command for administrators."""
    await show_moderation_user_list(
        message,
        AdminCommand.KICK,
        translator,
        command_bus,
        settings,
        report_service,
        cache_service,
        user_settings_service,
    )


@admin_router.message(Command("ban"), IsAdmin())
async def on_ban_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    command_bus: Annotated[CommandBus, FromDishka()],
    settings: Annotated[Settings, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
    cache_service: Annotated[CacheService, FromDishka()],
    user_settings_service: Annotated[UserSettingsService, FromDishka()],
) -> None:
    """Handles the /ban command for administrators."""
    await show_moderation_user_list(
        message,
        AdminCommand.BAN,
        translator,
        command_bus,
        settings,
        report_service,
        cache_service,
        user_settings_service,
    )


@admin_router.message(Command("subscribers"), IsAdmin())
async def on_subscribers_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
) -> None:
    """Handles the /subscribers command for administrators."""
    _ = translator.gettext

    result = await report_service.get_subscribers_info(page=0)

    await display_paginated_list(
        target=message,
        bot=bot,
        translator=translator,
        items_on_page=result.items,
        total_items=result.total_items,
        page=result.current_page,
        title_text=_("Here is the list of subscribers."),
        empty_list_text=_("No subscribers found."),
        keyboard_factory=create_subscriber_list_keyboard,
        keyboard_factory_kwargs={},
    )


@admin_router.message(Command("unban"), IsAdmin())
async def on_unban_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
) -> None:
    """Handles the /unban command for administrators."""
    _ = translator.gettext

    result = await report_service.get_banned_users_info(page=0)

    await display_paginated_list(
        target=message,
        bot=bot,
        translator=translator,
        items_on_page=result.items,
        total_items=result.total_items,
        page=result.current_page,
        title_text=_("Banned Users"),
        empty_list_text=_("The ban list is empty."),
        keyboard_factory=create_banned_user_list_keyboard,
        keyboard_factory_kwargs={},
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
