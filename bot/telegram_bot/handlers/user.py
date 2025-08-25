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
from bot.config import Settings
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.report_service import ReportService
from bot.services.user_settings_service import UserSettingsService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.formatters import get_effective_server_name
from bot.telegram_bot.api import safe_delete_message
from bot.telegram_bot.filters.subscription import IsSubscribed
from bot.telegram_bot.formatters import (
    format_who_message,
    group_users_for_who_command,
)
from bot.telegram_bot.keyboards import (
    create_main_menu_keyboard,
    create_main_settings_keyboard,
)
from bot.telegram_bot.types.bots import EventBot

logger = logging.getLogger(__name__)
user_commands_router = Router(name="user_commands_router")


@user_commands_router.message(CommandStart(deep_link=True, magic=F.args.as_("token")))
async def on_start_with_payload(
    message: Message,
    token: str,
    translator: Annotated[NullTranslations, FromDishka()],
    deeplink_service: Annotated[DeeplinkService, FromDishka()],
    settings: Annotated[Settings, FromDishka()],
) -> None:
    """Handle the /start command with a deeplink, using a magic filter."""
    _ = translator.gettext
    if not message.from_user:
        logger.warning("Cannot handle deeplink: message.from_user is None.")
        await message.reply(_("An error occurred. Please try again later."))
        return

    reply_text, success = await deeplink_service.process_telegram_deeplink(
        token=token,
        translator=translator,
        telegram_id=message.from_user.id,
        default_lang=settings.general.default_lang,
    )
    await message.reply(reply_text)


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
    bot: Annotated[EventBot, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
    cache: Annotated[CacheService, FromDishka()],
    user_settings_service: Annotated[UserSettingsService, FromDishka()],
    command_bus: Annotated[CommandBus, FromDishka()],
    settings: Annotated[Settings, FromDishka()],
    tt_connection: Annotated[TeamTalkConnection, FromDishka()],  # Added this line
) -> None:
    """Handles the /who command by calling the user service to generate a report."""
    _ = translator.gettext
    if not message.from_user:
        return

    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        is_admin = cache.is_admin(message.from_user.id)

        result = await report_service.get_telegram_who_report(
            telegram_user_id=message.from_user.id,
            translator=translator,
            cache_service=cache,
            user_settings_service=user_settings_service,
            command_bus=command_bus,
        )

        if not result.success:
            report_text = result.error_message or _("An error occurred.")
        else:
            server_name = get_effective_server_name(
                tt_connection.instance,
                translator,
                settings,  # Changed this line
            )
            grouped_data, total_users = group_users_for_who_command(
                result.users,
                None,  # bot_user_id is not needed for formatting here
                is_caller_admin=is_admin,
                translator=translator,
            )
            report_text = format_who_message(
                grouped_data,
                total_users,
                translator=translator,
                server_host=server_name,
            )

        await message.reply(report_text)


@user_commands_router.message(Command("help"), IsSubscribed())
async def on_help_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    cache: Annotated[CacheService, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
) -> None:
    """Handles the /help command, showing available commands."""
    if not message.from_user:
        return

    is_admin = cache.is_admin(message.from_user.id)
    help_text = report_service.get_help_text(translator, is_admin=is_admin)
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
