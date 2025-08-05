"""Telegram bot command handlers for regular user interactions."""

import gettext  # For type hinting translator
import logging

# For type hinting Services
from typing import (
    TYPE_CHECKING,  # For admin_ids_cache type hint
    cast,
)

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession

# Import SQLModel's AsyncSession for casting
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from bot.core.utils import build_help_message
from bot.models import UserSettings
from bot.services import user_service
from bot.teamtalk_bot.connection import TeamTalkConnection  # For type hinting
from bot.telegram_bot.deeplink import handle_deeplink
from bot.telegram_bot.keyboards import create_main_menu_keyboard, create_main_settings_keyboard
from bot.telegram_bot.utils import safe_delete_message

if TYPE_CHECKING:
    from bot.services_container import Services

# Middlewares to apply
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware

logger = logging.getLogger(__name__)
user_commands_router = Router(name="user_commands_router")
# Apply to the whole router. Specific handlers will use or not use tt_connection.
user_commands_router.message.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
user_commands_router.message.middleware(TeamTalkConnectionCheckMiddleware())


@user_commands_router.message(CommandStart(deep_link=False))
async def on_start_command(
    message: Message,
    translator: gettext.GNUTranslations,
) -> None:
    """Handles the /start command without a deeplink."""
    _ = translator.gettext
    await message.reply(_("Hello! Use /help to see available commands."))


@user_commands_router.message(CommandStart(deep_link=True, magic=F.args.as_("token")))
async def on_start_with_payload(
    message: Message,
    token: str,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    services: "Services",
) -> None:
    """Handles the /start command with a deeplink, extracting the token via a magic filter."""
    if not message.from_user:
        return

    await handle_deeplink(message, token, cast(SQLModelAsyncSession, session), translator, user_settings, services)


@user_commands_router.message(Command("who"))
async def on_who_command(
    message: Message,
    translator: "gettext.GNUTranslations",
    services: "Services",
    tt_connection: TeamTalkConnection,  # Middleware ensures tt_connection is not None
    bot: Bot,
) -> None:
    """Handles the /who command by calling the user service to generate a report."""
    if not message.from_user:
        return

    # Use ChatActionSender to show "typing..." status
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        is_admin = services.cache.is_admin(message.from_user.id)

        report_text = await user_service.get_online_users_report(
            tt_connection=tt_connection, is_caller_admin=is_admin, translator=translator
        )

        await message.reply(report_text)


@user_commands_router.message(Command("help"))
async def on_help_command(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    services: "Services",  # Injected from workflow_data
) -> None:
    """Handles the /help command, showing available commands."""
    _ = translator.gettext
    if not message.from_user:
        return

    is_telegram_admin = services.cache.is_admin(message.from_user.id)
    help_text = build_help_message(translator, "telegram", is_telegram_admin=is_telegram_admin, is_teamtalk_admin=False)
    await message.reply(help_text)


@user_commands_router.message(Command("settings"))
async def on_settings_command(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
) -> None:
    """Handles the /settings command, showing the main settings menu."""
    _ = translator.gettext
    if not message.from_user:
        return

    await safe_delete_message(message, log_context_message="user settings command")
    settings_builder = await create_main_settings_keyboard(translator)
    try:
        await message.answer(text=_("Settings"), reply_markup=settings_builder.as_markup())
    except TelegramAPIError:
        logger.exception("Could not send settings menu.")


@user_commands_router.message(Command("menu"))
async def on_menu_command(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    services: "Services",  # Injected from workflow_data
) -> None:
    """Handles the /menu command, showing the main command menu."""
    _ = translator.gettext
    if not message.from_user:
        return

    await safe_delete_message(message, log_context_message="user menu command")
    is_admin = services.cache.is_admin(message.from_user.id)
    # Pass the full translator object to create_main_menu_keyboard
    menu_builder = await create_main_menu_keyboard(translator, is_admin=is_admin)
    try:
        await message.answer(text=_("Main Menu:"), reply_markup=menu_builder.as_markup())
    except TelegramAPIError:
        logger.exception("Could not send main menu.")
